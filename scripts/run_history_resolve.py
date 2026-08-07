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
  * The panel is fetched with `mask_stale_tail=True`: a delisted ticker's tail must stay
    NaN. The default ffill freezes its last close to the panel end, and every open horizon
    then measures a flat, invented tail as a real outcome (measured 2026-08-07: a
    crash-then-delist produced a plausible r_12m of -0.4979 out of nothing). A ticker whose
    prices stop well before the panel end keeps its MEASURED horizons and has the rest
    buried as `no_price_history` — plan Decision 4's exact case (a partially measured event
    later found delisted stays partially measured).
  * A window that reaches past the panel end stays OPEN; only the elapsed horizons are
    written (storage resolution is per-column, so a later run fills the rest).
  * A chunk whose fetch fails, whose panel comes back without the benchmark, is empty or
    has a duplicated index is counted and skipped WHOLE — those are real transient
    defects (Yahoo throttles per IP; see data/fetch.py and the 2026-07-14 incident) and
    burying their tickers would manufacture survivorship gaps out of a network hiccup.
    Every missing ticker otherwise gets one single-ticker re-check before it is buried;
    that probe, not the batch result, is the throttle-vs-delisted discriminator.
  * `max_missing_share` (the chunk-level "too many missing at once smells like throttling"
    heuristic) is WRONG on a mortality-heavy queue and defaults to off for this job. A
    20-year universe is alphabetically clustered by death: measured on the first real run,
    32-94 % of a chunk's tickers were genuinely delisted, the guard read that as throttling
    and skipped the chunk whole. Worse, it DIVERGES — every live name that resolves out
    raises the dead share of what remains, so pass 1 measured 4/180 chunks and pass 2
    measured 0/177, ending at 2.9 % coverage with the dead names parked in "never
    evaluated" instead of the survivorship bucket. Run history with
    `--max-missing-share 1.0 --max-rechecks 50`; the guard survives only for callers whose
    queue is mostly-alive, and the per-ticker probe (with_retry backoff keeps it polite)
    does the real work.
  * A malformed `t0` or an unmappable symbol is COUNTED but never buried: both are
    fixable data/normalization bugs, not measured facts, and burial is irreversible.

The buckets describe the PLAN — what the measurement found. `written`/`refused` describe
what the database actually did; `refused > 0` means another run moved the same rows first.

Two-phase by design: `resolve_batch` plans (pure, no DB), `apply_plan` writes. Dry-run is
the default — `--apply` writes, per the `fix_*`/backfill script convention.

Usage:
    uv run python scripts/run_history_resolve.py [--db equity_scout.db] [--limit N] [--apply]
    # the history queue (mortality-heavy — see the missing-share note above):
    uv run python scripts/run_history_resolve.py --apply --max-missing-share 1.0 --max-rechecks 50
"""
from __future__ import annotations

import argparse
import re
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
# Trading days per stored horizon column.
HISTORY_HORIZONS = {"r_1w": 5, "r_1m": 21, "r_3m": 63, "r_6m": 126, "r_12m": 252}
# A horizon this script cannot measure would leave rows in `resolved_partially` forever, so
# lock the mapping to the storage contract at import time rather than discovering it in a run.
assert set(HISTORY_HORIZONS) <= set(RETURN_HORIZONS), "HISTORY_HORIZONS must be storage columns"

TICKER_CHUNK = 50  # yfinance batches: big enough to be fast, small enough to stay under throttling
PANEL_LEAD_IN_DAYS = 10  # so the panel reaches back to t0 itself (weekend/holiday filings)
# A ticker is treated as DEAD only once the panel has run this many sessions past its last
# real close (~1 trading month). Below that, the tail is indistinguishable from a trading
# HALT (takeover review, regulatory investigation, foreign listing idle over a local
# holiday, provider lagging the US close) — and burial is irreversible. The margin is free
# here: this is a backfill over events that are years old, so a genuinely delisted name
# clears a month by miles, while a halted one gets resolved once it trades again.
STALE_TAIL_SESSIONS = 21
# Above this share of requested tickers coming back column-less, the whole chunk is suspect
# (throttling), not the tickers. Only applied to chunks big enough for the share to mean
# something; smaller chunks go straight to the per-ticker re-check. Valid ONLY for a
# mostly-alive queue — see the module docstring for the divergence this caused on the
# 20-year history queue, and pass 1.0 (via --max-missing-share) to switch it off.
MAX_MISSING_SHARE = 0.30
MIN_CHUNK_FOR_SHARE_GUARD = 4
# Re-checks are serial single-ticker fetches, each up to 3 attempts with a 30-60s rate-limit
# backoff. A moderate throttle (just under MAX_MISSING_SHARE) across ~900 chunks would
# otherwise add hours of wall clock, so the tail beyond this cap is left OPEN and counted —
# the next run retries it. Unverified absence is never a burial.
MAX_RECHECKS_PER_CHUNK = 8
# Dots mean two different things: a US share class (BRK.B -> BRK-B, Yahoo's convention) and
# an exchange suffix (BMW.DE, PETR4.SA), which `yf_symbol` would mangle into a symbol that
# exists nowhere. Only the share-class shape is mapped; the rest is reported, never buried.
_SHARE_CLASS = re.compile(r"^[A-Z]+\.[A-Z]$")

REASON_NO_PRICE_HISTORY = "no_price_history"
REASON_PANEL_GAP = "panel_gap"
REASON_BENCHMARK_SELF = "benchmark_self"

BUCKET_RESOLVED = "resolved_fully"
BUCKET_PARTIAL = "resolved_partially"
BUCKET_RESOLVED_THEN_BURIED = "resolved_then_buried"
BUCKET_STILL_OPEN = "still_open_no_new_windows"
BUCKET_NO_PRICE_HISTORY = "unresolvable_no_price_history"
BUCKET_PANEL_GAP = "unresolvable_panel_gap"
BUCKET_BENCHMARK_SELF = "unresolvable_benchmark_self"
BUCKET_UNMAPPABLE_SYMBOL = "unmappable_symbol"
BUCKET_BAD_T0 = "bad_t0"
BUCKET_FETCH_FAILED = "fetch_failed"
BUCKET_RECHECK_CAPPED = "recheck_capped"
BUCKETS = (
    BUCKET_RESOLVED, BUCKET_PARTIAL, BUCKET_RESOLVED_THEN_BURIED, BUCKET_STILL_OPEN,
    BUCKET_NO_PRICE_HISTORY, BUCKET_PANEL_GAP, BUCKET_BENCHMARK_SELF,
    BUCKET_UNMAPPABLE_SYMBOL, BUCKET_BAD_T0, BUCKET_FETCH_FAILED, BUCKET_RECHECK_CAPPED,
)


@dataclass(frozen=True)
class Resolution:
    """One event's outcome: the horizons newly measured this run, or why none were.

    `returns` and `unresolvable_reason` can BOTH be set — a delisted ticker keeps its
    measured horizons and has the unreachable ones buried (plan Decision 4)."""

    event_id: int
    bucket: str
    returns: dict[str, float]  # horizons measured THIS run (never ones already stored)
    unresolvable_reason: str | None  # set iff the remaining horizons are to be buried


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


def panel_symbol(ticker: str) -> str | None:
    """The stored ticker as a yfinance panel column, or None if it cannot be mapped."""
    raw = (ticker or "").strip().upper()
    if "." in raw and not _SHARE_CLASS.match(raw):
        return None
    return yf_symbol(raw) if raw else None


def _resolve_one(event: dict, panel: pd.DataFrame) -> Resolution:
    event_id = int(event["id"])
    at = _panel_timestamp(event.get("t0"))
    if at is None:
        return Resolution(event_id, BUCKET_BAD_T0, {}, None)
    symbol = panel_symbol(str(event["ticker"]))
    if symbol is None:
        return Resolution(event_id, BUCKET_UNMAPPABLE_SYMBOL, {}, None)
    if symbol == BENCHMARK:
        # "SPY vs SPY" has no measurable edge, and panel[[SPY, SPY]] is a duplicate-column
        # frame that breaks the pair-wise math (same guard as person_track.score_persons).
        return Resolution(event_id, BUCKET_BENCHMARK_SELF, {}, REASON_BENCHMARK_SELF)
    if symbol not in panel.columns:
        return Resolution(event_id, BUCKET_NO_PRICE_HISTORY, {}, REASON_NO_PRICE_HISTORY)
    pair = panel[[symbol, BENCHMARK]].dropna()  # both legs on one calendar, no interior gaps
    if len(pair) == 0 or pair.index[0] > at:
        return Resolution(event_id, BUCKET_PANEL_GAP, {}, REASON_PANEL_GAP)
    # With `mask_stale_tail=True` a delisted ticker's prices simply stop; the panel keeps
    # running. Sessions past its last close are the delisting evidence.
    dead = len(panel.index[panel.index > pair.index[-1]]) > STALE_TAIL_SESSIONS

    on_or_after = pair.index[pair.index >= at]
    if len(on_or_after) == 0:  # t0 lies past this ticker's last price
        if dead:
            return Resolution(event_id, BUCKET_NO_PRICE_HISTORY, {}, REASON_NO_PRICE_HISTORY)
        return Resolution(event_id, BUCKET_STILL_OPEN, {}, None)  # t0 past the panel end
    entry = on_or_after[0]
    stored = {horizon for horizon in RETURN_HORIZONS if event.get(horizon) is not None}
    measured = {}
    for horizon, days in HISTORY_HORIZONS.items():
        if horizon in stored:
            continue  # per-column one-way: an earlier run's value stands
        rel = relative_forward_return(pair[symbol], pair[BENCHMARK], entry, days)
        if rel is not None:
            measured[horizon] = float(rel)

    remaining = set(RETURN_HORIZONS) - stored - set(measured)
    if not remaining:
        return Resolution(event_id, BUCKET_RESOLVED, measured, None)
    if dead:
        # The ticker stopped trading: the open windows can never be measured. Keep what IS
        # measured and bury only the rest — the per-column store supports exactly this.
        # `stored` counts too: a row whose horizons were measured in an EARLIER run is just
        # as partially-measured as one measured now, and must not be reported as a pure
        # survivorship gap only because this run happened to add nothing.
        bucket = BUCKET_RESOLVED_THEN_BURIED if (measured or stored) else BUCKET_NO_PRICE_HISTORY
        return Resolution(event_id, bucket, measured, REASON_NO_PRICE_HISTORY)
    if not measured:
        return Resolution(event_id, BUCKET_STILL_OPEN, {}, None)
    return Resolution(event_id, BUCKET_PARTIAL, measured, None)


def resolve_batch(events: list[dict], panel: pd.DataFrame, *, now: str) -> BatchPlan:
    """Plan the resolution of `events` against a close panel (pure — nothing is written).

    `events` are `unresolved_events` rows (their r_* values say which horizons an earlier
    run already wrote); `panel` is a close DataFrame that MUST contain the benchmark and at
    least one row — measuring "relative" without the benchmark would be a silent absolute
    return, so a broken panel is a loud error, never a per-event skip (its events would all
    look like survivorship gaps). The panel is expected to come from a `mask_stale_tail=True`
    load; with a plain ffill, delisted tails silently resolve as real measurements.
    """
    if BENCHMARK not in panel.columns:
        raise ValueError(f"benchmark {BENCHMARK} missing from the price panel")
    if panel.empty:
        raise ValueError("price panel is empty")
    return BatchPlan(now=now, resolutions=[_resolve_one(event, panel) for event in events])


def apply_plan(db_path: str, plan: BatchPlan) -> dict:
    """Execute a plan. Returns {written, refused} counting STORAGE TRANSITIONS, not events —
    a delisted event both writes its measured horizons and buries the rest, in that order
    (`mark_resolved` refuses any write to an already-buried row). `refused` counts storage
    no-ops (a column another run already filled, a row already buried) instead of hiding them.
    """
    written = 0
    refused = 0

    def _count(ok: bool) -> None:
        nonlocal written, refused
        written += int(ok)
        refused += int(not ok)

    for resolution in plan.resolutions:
        if resolution.returns:
            _count(mark_resolved(db_path, resolution.event_id, resolution.returns, now=plan.now))
        if resolution.unresolvable_reason is not None:
            _count(mark_unresolvable(
                db_path, resolution.event_id, resolution.unresolvable_reason, now=plan.now
            ))
    return {"written": written, "refused": refused}


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _panel_defect(closes: pd.DataFrame) -> str | None:
    """Why this panel must not be measured against, or None if it is usable."""
    if closes.empty:
        return "leeres Panel"
    if BENCHMARK not in closes.columns:
        return f"Benchmark {BENCHMARK} fehlt"
    if closes.index.has_duplicates:
        return "doppelte Handelstage im Index"
    return None


def run_history_resolve(
    db_path: str,
    *,
    now: str,
    fetch_prices: Callable[[list[str], str], PricePanel],
    limit: int | None = None,
    apply: bool = False,
    chunk_size: int = TICKER_CHUNK,
    max_rechecks: int = MAX_RECHECKS_PER_CHUNK,
    max_missing_share: float = MAX_MISSING_SHARE,
) -> dict:
    """Resolve the open history queue in ticker chunks. Returns the run's full accounting.

    Events are grouped by their yfinance symbol so one fetch serves every event of a
    ticker; each chunk is fetched from the earliest t0 in it (minus a lead-in) so no event
    is measured against a panel that starts too late. Events with an unusable t0 or symbol
    never enter the chunking at all — a junk date must not skew a fetch window.

    `max_missing_share = 1.0` switches off the chunk-level share heuristic so every missing
    ticker is decided by its own re-check (what the history queue needs, see the module
    docstring); the panel-defect skip is untouched by it and stays the transient guard.
    """
    events = unresolved_events(db_path, limit)
    counts: Counter[str] = Counter({bucket: 0 for bucket in BUCKETS})
    written = 0
    refused = 0

    by_symbol: dict[str, list[dict]] = {}
    for event in events:
        symbol = panel_symbol(str(event["ticker"]))
        if _panel_timestamp(event.get("t0")) is None:
            counts[BUCKET_BAD_T0] += 1
            print(f"Ungültiges t0 (Event {event['id']}, {event['ticker']}): {event.get('t0')!r}")
        elif symbol is None:
            counts[BUCKET_UNMAPPABLE_SYMBOL] += 1
            print(f"Symbol nicht abbildbar (Event {event['id']}): {event['ticker']!r}")
        else:
            by_symbol.setdefault(symbol, []).append(event)

    chunks = list(_chunks(sorted(by_symbol), chunk_size))
    for number, chunk in enumerate(chunks, start=1):
        head = f"Chunk {number}/{len(chunks)} [{chunk[0]}..{chunk[-1]}], {len(chunk)} Ticker"
        chunk_events = [event for symbol in chunk for event in by_symbol[symbol]]
        earliest = min(_panel_timestamp(event["t0"]) for event in chunk_events)
        start = (earliest - pd.Timedelta(days=PANEL_LEAD_IN_DAYS)).date().isoformat()

        try:
            closes = fetch_prices(sorted(set(chunk) | {BENCHMARK}), start).closes
        except Exception as exc:  # noqa: BLE001 - provider errors are opaque; count, never bury
            counts[BUCKET_FETCH_FAILED] += len(chunk_events)
            print(f"{head}, {len(chunk_events)} Events: Fetch fehlgeschlagen ({exc!r}) — offen.")
            continue
        defect = _panel_defect(closes)
        if defect is not None:
            counts[BUCKET_FETCH_FAILED] += len(chunk_events)
            print(f"{head}, {len(chunk_events)} Events: Panel unbrauchbar ({defect}) — offen.")
            continue

        active = list(chunk)
        missing = [symbol for symbol in chunk if symbol not in closes.columns]
        if (
            missing
            and len(chunk) >= MIN_CHUNK_FOR_SHARE_GUARD
            and len(missing) / len(chunk) > max_missing_share
        ):
            # Mass failure smells like throttling — unless the queue is mortality-heavy, in
            # which case it is just an alphabetical cluster of dead names (see the docstring).
            counts[BUCKET_FETCH_FAILED] += len(chunk_events)
            print(f"{head}, {len(chunk_events)} Events: {len(missing)} Ticker ohne Spalte"
                  f" (>{max_missing_share:.0%}) — Drosselung vermutet, offen.")
            continue
        for symbol in missing[max_rechecks:]:
            # Beyond the cap: absence unverified, so the events wait for the next run.
            active.remove(symbol)
            counts[BUCKET_RECHECK_CAPPED] += len(by_symbol[symbol])
        if len(missing) > max_rechecks:
            print(f"{head}: {len(missing) - max_rechecks} fehlende Ticker über dem"
                  f" Nachprüf-Limit ({max_rechecks}) — offen für den nächsten Lauf.")
        for symbol in missing[:max_rechecks]:
            # One targeted retry before an irreversible burial: a single-ticker fetch that
            # also comes back empty is real absence, not a batch hiccup.
            try:
                single = fetch_prices([symbol, BENCHMARK], start).closes
            except Exception as exc:  # noqa: BLE001 - provider errors are opaque
                single, single_defect = None, repr(exc)
            else:
                single_defect = _panel_defect(single)
            if single_defect is not None:  # absence unverified — the events stay open
                active.remove(symbol)
                counts[BUCKET_FETCH_FAILED] += len(by_symbol[symbol])
                print(f"{head}: Nachprüfung {symbol} ohne Ergebnis ({single_defect}) — offen.")
                continue
            if single is not None and symbol in single.columns:
                # Left join keeps the chunk's calendar; the pair-wise dropna handles the rest.
                closes = closes.join(single[[symbol]], how="left")
                print(f"{head}: {symbol} erst im Einzel-Fetch geliefert — nicht begraben.")

        chunk_events = [event for symbol in active for event in by_symbol[symbol]]
        if not chunk_events:
            print(f"{head}: keine auswertbaren Events übrig.")
            continue
        plan = resolve_batch(chunk_events, closes, now=now)
        chunk_counts = plan.counts()
        counts.update(chunk_counts)
        if apply:
            applied = apply_plan(db_path, plan)
            written += applied["written"]
            refused += applied["refused"]
        outcome = ", ".join(
            f"{bucket}={value}" for bucket, value in chunk_counts.items() if value
        )
        print(f"{head}, {len(chunk_events)} Events: {outcome or 'nichts zu tun'}.")

    return {
        "events": len(events),
        "counts": {bucket: counts[bucket] for bucket in BUCKETS},
        "written": written,
        "refused": refused,
        "applied": apply,
        "still_open": len(unresolved_events(db_path)),
    }


def format_summary(result: dict) -> str:
    """Per-run summary in the Wave-1 style, extended so every bucket is visible.

    `resolved_then_buried` is deliberately counted in BOTH headline aggregates: such a row
    really is measured (its elapsed horizons are real numbers the study uses) AND really is
    a survivorship gap (its open horizons never happened). The two aggregates therefore do
    not sum to the event count — `Ereignisse in diesem Lauf` is the denominator.
    """
    counts = result["counts"]
    resolved = counts[BUCKET_RESOLVED] + counts[BUCKET_PARTIAL] + counts[BUCKET_RESOLVED_THEN_BURIED]
    no_price = counts[BUCKET_NO_PRICE_HISTORY] + counts[BUCKET_RESOLVED_THEN_BURIED]
    unresolvable = no_price + counts[BUCKET_PANEL_GAP] + counts[BUCKET_BENCHMARK_SELF]
    lines = [
        f"Aufgelöst: {resolved} (vollständig: {counts[BUCKET_RESOLVED]},"
        f" teilweise: {counts[BUCKET_PARTIAL]},"
        f" teilweise+delisted: {counts[BUCKET_RESOLVED_THEN_BURIED]}),"
        f" unresolvable: {unresolvable}"
        f" (davon no_price_history: {no_price},"
        f" panel_gap: {counts[BUCKET_PANEL_GAP]},"
        f" benchmark_self: {counts[BUCKET_BENCHMARK_SELF]}),"
        f" offen: {result['still_open']}.",
        f"Ereignisse in diesem Lauf: {result['events']} — ohne neues Fenster:"
        f" {counts[BUCKET_STILL_OPEN]}, Fetch fehlgeschlagen: {counts[BUCKET_FETCH_FAILED]},"
        f" ungültiges t0: {counts[BUCKET_BAD_T0]},"
        f" Symbol nicht abbildbar: {counts[BUCKET_UNMAPPABLE_SYMBOL]},"
        f" Nachprüfung gedeckelt: {counts[BUCKET_RECHECK_CAPPED]};"
        f" geschrieben: {result['written']}, abgelehnt: {result['refused']}.",
    ]
    if not result["applied"]:
        lines.append("Dry-Run — nichts geschrieben. Mit --apply schreiben.")
    return "\n".join(lines)


def _fetch_price_panel(tickers: list[str], start: str) -> PricePanel:
    """Network default: daily closes for one ticker chunk + SPY from `start`.

    Column-wise (`load_price_history`, not `load_etf_panel`): history tickers are global
    and heterogeneous, so one young or dead symbol must not truncate every other ticker's
    range — the common-range trim would silently manufacture `panel_gap`s. `mask_stale_tail`
    is the study's core honesty switch (see the module docstring). Wrapped in `with_retry`
    because this job walks thousands of tickers and Yahoo throttles per IP. Lazy imports
    keep the network out of import time and tests.
    """
    from equity_scout.data.etf_panel import load_price_history
    from equity_scout.data.fetch import with_retry

    def _load() -> PricePanel:
        return load_price_history(
            tickers, start=start, snapshot=HISTORY_SNAPSHOT, refresh=True, mask_stale_tail=True
        )

    return with_retry(_load, attempts=3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--limit", type=int, default=None,
                        help="resolve at most N open events (incremental runs)")
    parser.add_argument("--apply", action="store_true",
                        help="write the results (default: dry-run, measure and report only)")
    parser.add_argument(
        "--max-missing-share", type=float, default=MAX_MISSING_SHARE,
        help="skip a chunk whole above this share of column-less tickers; 1.0 disables the"
             " heuristic and decides every missing ticker by its own re-check (use 1.0 for"
             f" the history queue, see the module docstring; default {MAX_MISSING_SHARE})",
    )
    parser.add_argument(
        "--max-rechecks", type=int, default=MAX_RECHECKS_PER_CHUNK,
        help="single-ticker re-checks per chunk before the rest is left open"
             f" (default {MAX_RECHECKS_PER_CHUNK}; raise it for dead-heavy chunks)",
    )
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_history_resolve(
        args.db, now=now, fetch_prices=_fetch_price_panel, limit=args.limit, apply=args.apply,
        max_rechecks=args.max_rechecks, max_missing_share=args.max_missing_share,
    )
    print(format_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
