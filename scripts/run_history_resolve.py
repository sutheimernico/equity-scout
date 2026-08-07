"""Resolve historical catalyst events against realized forward returns vs SPY (P2a Task 5).

Batch counterpart of the live `run_resolve_predictions.py`: for every open row in
`historical_events`, measure the ticker's forward return minus SPY's over the same window
at 1w/1m/3m/6m/12m trading days, starting at the FIRST panel date on/after `t0` (the day
the fact became publicly knowable). The return math itself is never reimplemented here —
it is `ml.entry_eval.relative_forward_return`, the single source of truth the person track
record and the prediction ledger already measure with.

Honesty rules (the study's coverage numbers are built on them):
  * Panel starts AFTER t0 -> `panel_gap`, never a silently shifted measurement window.
    That shifted window was the Wave-1 bug (plans/2026-08-05-v15-wave1-resolve-honesty.md).
  * Ticker absent from the panel -> `no_price_history`, the survivorship bucket. Delisted
    and renamed names are COUNTED, which is exactly what the report's disclaimer needs.
  * A window that reaches past the panel end stays OPEN; only the elapsed horizons are
    written (storage resolution is per-column, so a later run fills the rest).
  * A chunk whose fetch fails (or whose panel comes back without the benchmark) is counted
    and skipped whole — a provider outage must never be buried as a survivorship gap.
  * Every event touched by a run lands in exactly ONE bucket; the counters are derived
    from the resolution list itself, so they cannot drift apart from what happened.

Two-phase by design: `resolve_batch` plans (pure, no DB), `apply_plan` writes. Dry-run is
the default — `--apply` writes, per the `fix_*`/backfill script convention.

Usage:
    uv run python scripts/run_history_resolve.py [--db equity_scout.db] [--limit N] [--apply]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.historical_storage import (
    RETURN_HORIZONS,
    mark_resolved,
    mark_unresolvable,
    unresolved_events,
)
from equity_scout.evidence.person_track import yf_symbol
from equity_scout.market import PricePanel
from equity_scout.ml.entry_eval import relative_forward_return

BENCHMARK = "SPY"
# Distinct snapshot so the multi-year history fetch never clobbers the training/backtest/
# live-resolve panels (each chunk overwrites it — it is a debugging artefact, not a cache;
# `refresh=True` means the run never reads it back).
HISTORY_SNAPSHOT = "data/prices/history_panel.csv"
# Trading days per stored horizon column. Keys must stay a subset of RETURN_HORIZONS.
HORIZON_DAYS = {"r_1w": 5, "r_1m": 21, "r_3m": 63, "r_6m": 126, "r_12m": 252}
TICKER_CHUNK = 50  # yfinance batches: big enough to be fast, small enough to stay under throttling
PANEL_LEAD_IN_DAYS = 10  # so the panel reaches back to t0 itself (weekend/holiday filings)

REASON_NO_PRICE_HISTORY = "no_price_history"
REASON_PANEL_GAP = "panel_gap"
REASON_BENCHMARK_SELF = "benchmark_self"

BUCKET_RESOLVED = "resolved_fully"
BUCKET_PARTIAL = "resolved_partially"
BUCKET_STILL_OPEN = "still_open_no_new_windows"
BUCKET_NO_PRICE_HISTORY = "unresolvable_no_price_history"
BUCKET_PANEL_GAP = "unresolvable_panel_gap"
BUCKET_BENCHMARK_SELF = "unresolvable_benchmark_self"
BUCKET_BAD_T0 = "bad_t0"
BUCKET_FETCH_FAILED = "fetch_failed"
BUCKETS = (
    BUCKET_RESOLVED, BUCKET_PARTIAL, BUCKET_STILL_OPEN, BUCKET_NO_PRICE_HISTORY,
    BUCKET_PANEL_GAP, BUCKET_BENCHMARK_SELF, BUCKET_BAD_T0, BUCKET_FETCH_FAILED,
)


@dataclass(frozen=True)
class Resolution:
    """One event's outcome: the horizons newly measured this run, or why none were."""

    event_id: int
    bucket: str
    returns: dict[str, float]  # horizons measured THIS run (never ones already stored)
    unresolvable_reason: str | None  # set iff the event is to be buried


@dataclass(frozen=True)
class BatchPlan:
    """A complete, timestamped write instruction. `now` travels with the plan so the
    measurement stays clock-free and `apply_plan` needs no second injection point."""

    now: str
    resolutions: list[Resolution]

    def counts(self) -> dict[str, int]:
        """Bucket histogram — derived from the resolutions, so it always sums to len()."""
        histogram = Counter(resolution.bucket for resolution in self.resolutions)
        return {bucket: histogram.get(bucket, 0) for bucket in BUCKETS}


def _panel_timestamp(t0: str | None) -> pd.Timestamp | None:
    """`t0` (a plain ISO date, plan Decision 10) as a tz-naive midnight timestamp to match
    the panel index. None for anything unparseable — a malformed row is counted, not fatal."""
    try:
        ts = pd.Timestamp(t0)
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def _resolve_one(event: dict, panel: pd.DataFrame) -> Resolution:
    event_id = int(event["id"])
    at = _panel_timestamp(event.get("t0"))
    if at is None:
        return Resolution(event_id, BUCKET_BAD_T0, {}, None)
    symbol = yf_symbol(str(event["ticker"]))
    if symbol == BENCHMARK:
        # "SPY vs SPY" has no measurable edge, and panel[[SPY, SPY]] is a duplicate-column
        # frame that breaks the pair-wise math (same guard as person_track.score_persons).
        return Resolution(event_id, BUCKET_BENCHMARK_SELF, {}, REASON_BENCHMARK_SELF)
    if symbol not in panel.columns:
        return Resolution(event_id, BUCKET_NO_PRICE_HISTORY, {}, REASON_NO_PRICE_HISTORY)
    pair = panel[[symbol, BENCHMARK]].dropna()  # both legs on one calendar, no interior gaps
    if len(pair) == 0 or pair.index[0] > at:
        return Resolution(event_id, BUCKET_PANEL_GAP, {}, REASON_PANEL_GAP)
    on_or_after = pair.index[pair.index >= at]
    if len(on_or_after) == 0:
        return Resolution(event_id, BUCKET_STILL_OPEN, {}, None)  # t0 past the panel end
    entry = on_or_after[0]
    stored = {horizon for horizon in RETURN_HORIZONS if event.get(horizon) is not None}
    measured = {}
    for horizon, days in HORIZON_DAYS.items():
        if horizon in stored:
            continue  # per-column one-way: an earlier run's value stands
        rel = relative_forward_return(pair[symbol], pair[BENCHMARK], entry, days)
        if rel is not None:
            measured[horizon] = float(rel)
    if not measured:
        return Resolution(event_id, BUCKET_STILL_OPEN, {}, None)
    complete = len(stored | set(measured)) == len(RETURN_HORIZONS)
    return Resolution(event_id, BUCKET_RESOLVED if complete else BUCKET_PARTIAL, measured, None)


def resolve_batch(events: list[dict], panel: pd.DataFrame, *, now: str) -> BatchPlan:
    """Plan the resolution of `events` against a close panel (pure — nothing is written).

    `events` are `unresolved_events` rows (their r_* values say which horizons an earlier
    run already wrote); `panel` is a close DataFrame that MUST contain the benchmark —
    measuring "relative" without it would be a silent absolute return, so its absence is a
    loud error, never a per-event skip.
    """
    if BENCHMARK not in panel.columns:
        raise ValueError(f"benchmark {BENCHMARK} missing from the price panel")
    return BatchPlan(now=now, resolutions=[_resolve_one(event, panel) for event in events])


def apply_plan(db_path: str, plan: BatchPlan) -> dict:
    """Execute a plan. Returns {written, refused}; `refused` counts storage no-ops (a
    column another run already filled, a row already buried) — surfaced, not swallowed."""
    written = 0
    refused = 0
    for resolution in plan.resolutions:
        if resolution.unresolvable_reason is not None:
            ok = mark_unresolvable(
                db_path, resolution.event_id, resolution.unresolvable_reason, now=plan.now
            )
        elif resolution.returns:
            ok = mark_resolved(db_path, resolution.event_id, resolution.returns, now=plan.now)
        else:
            continue  # still open or malformed: nothing to write, by design
        written += int(ok)
        refused += int(not ok)
    return {"written": written, "refused": refused}


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def run_history_resolve(
    db_path: str,
    *,
    now: str,
    fetch_prices: Callable[[list[str], str], PricePanel],
    limit: int | None = None,
    apply: bool = False,
    chunk_size: int = TICKER_CHUNK,
) -> dict:
    """Resolve the open history queue in ticker chunks. Returns the run's full accounting.

    Events are grouped by their yfinance symbol so one fetch serves every event of a
    ticker; each chunk is fetched from the earliest t0 in it (minus a lead-in) so no event
    is measured against a panel that starts too late.
    """
    events = unresolved_events(db_path, limit)
    counts: Counter[str] = Counter({bucket: 0 for bucket in BUCKETS})
    written = 0
    refused = 0

    by_symbol: dict[str, list[dict]] = {}
    for event in events:
        if _panel_timestamp(event.get("t0")) is None:
            # Kept out of the chunking so a junk date cannot skew a fetch window.
            counts[BUCKET_BAD_T0] += 1
            print(f"Ungültiges t0 (Event {event['id']}, {event['ticker']}): {event.get('t0')!r}")
            continue
        by_symbol.setdefault(yf_symbol(str(event["ticker"])), []).append(event)

    for chunk in _chunks(sorted(by_symbol), chunk_size):
        chunk_events = [event for symbol in chunk for event in by_symbol[symbol]]
        earliest = min(_panel_timestamp(event["t0"]) for event in chunk_events)
        start = (earliest - pd.Timedelta(days=PANEL_LEAD_IN_DAYS)).date().isoformat()
        try:
            panel = fetch_prices(sorted(set(chunk) | {BENCHMARK}), start)
            plan = resolve_batch(chunk_events, panel.closes, now=now)
        except Exception as exc:  # noqa: BLE001 - provider/panel failures are opaque
            # Loud and counted: these events stay OPEN for the next run. Burying them as
            # `no_price_history` would fake a survivorship gap out of a network hiccup.
            print(f"Chunk {chunk[0]}..{chunk[-1]} fehlgeschlagen ({exc!r}) — Events bleiben offen.")
            counts[BUCKET_FETCH_FAILED] += len(chunk_events)
            continue
        counts.update(plan.counts())
        if apply:
            applied = apply_plan(db_path, plan)
            written += applied["written"]
            refused += applied["refused"]

    return {
        "events": len(events),
        "counts": {bucket: counts[bucket] for bucket in BUCKETS},
        "written": written,
        "refused": refused,
        "applied": apply,
        "still_open": len(unresolved_events(db_path)),
    }


def format_summary(result: dict) -> str:
    """Per-run summary in the Wave-1 style, extended so every bucket is visible."""
    counts = result["counts"]
    resolved = counts[BUCKET_RESOLVED] + counts[BUCKET_PARTIAL]
    unresolvable = (
        counts[BUCKET_NO_PRICE_HISTORY] + counts[BUCKET_PANEL_GAP] + counts[BUCKET_BENCHMARK_SELF]
    )
    lines = [
        f"Aufgelöst: {resolved} (vollständig: {counts[BUCKET_RESOLVED]},"
        f" teilweise: {counts[BUCKET_PARTIAL]}), unresolvable: {unresolvable}"
        f" (davon no_price_history: {counts[BUCKET_NO_PRICE_HISTORY]},"
        f" panel_gap: {counts[BUCKET_PANEL_GAP]},"
        f" benchmark_self: {counts[BUCKET_BENCHMARK_SELF]}),"
        f" offen: {result['still_open']}.",
        f"Ereignisse in diesem Lauf: {result['events']} — ohne neues Fenster:"
        f" {counts[BUCKET_STILL_OPEN]}, Fetch fehlgeschlagen: {counts[BUCKET_FETCH_FAILED]},"
        f" ungültiges t0: {counts[BUCKET_BAD_T0]};"
        f" geschrieben: {result['written']}, abgelehnt: {result['refused']}.",
    ]
    if not result["applied"]:
        lines.append("Dry-Run — nichts geschrieben. Mit --apply schreiben.")
    return "\n".join(lines)


def _fetch_price_panel(tickers: list[str], start: str) -> PricePanel:
    """Network default: daily closes for one ticker chunk + SPY from `start`.

    Column-wise (`load_price_history`, not `load_etf_panel`): history tickers are global
    and heterogeneous, so one young or dead symbol must not truncate every other ticker's
    range — the common-range trim would silently manufacture `panel_gap`s. Wrapped in
    `with_retry` because this job walks thousands of tickers and Yahoo throttles per IP.
    Lazy imports keep the network out of import time and tests.
    """
    from equity_scout.data.etf_panel import load_price_history
    from equity_scout.data.fetch import with_retry

    def _load() -> PricePanel:
        return load_price_history(tickers, start=start, snapshot=HISTORY_SNAPSHOT, refresh=True)

    return with_retry(_load, attempts=3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--limit", type=int, default=None,
                        help="resolve at most N open events (incremental runs)")
    parser.add_argument("--apply", action="store_true",
                        help="write the results (default: dry-run, measure and report only)")
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_history_resolve(
        args.db, now=now, fetch_prices=_fetch_price_panel, limit=args.limit, apply=args.apply
    )
    print(format_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
