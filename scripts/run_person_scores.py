"""Person track-record CLI: measure every active filer/fund/insider against SPY,
persist scores.

Usage:
    python scripts/run_person_scores.py [--db equity_scout.db] [--lookback-years 3]

Pipeline: active congress filers from our evidence store -> their FULL purchase
history from the mirror's per-filer files (polite: only filers we actually see) ->
plus 13F fund calls AND Form 4 insider calls from our own store (no backfill for
either — their scores accumulate as the ledger resolves) -> one cached close panel ->
score_persons -> person_scores table. Calls older than the lookback are dropped AND
counted: the 540d recency half-life makes them near-weightless anyway, and the panel
stays bounded. Weekly cadence is plenty — the underlying disclosures lag 45/135 days
(insiders: 2 business days).
"""
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.base import SOURCE_13F, SOURCE_CONGRESS, SOURCE_INSIDER
from equity_scout.evidence.congress import fetch_filer_history
from equity_scout.evidence.person_storage import save_person_scores
from equity_scout.evidence.person_track import (
    Call,
    calls_from_events,
    calls_from_filer_payload,
    score_persons,
    yf_symbol,
)
from equity_scout.evidence.storage import events_in_window
from equity_scout.market import PricePanel

BENCHMARK = "SPY"
PERSONS_SNAPSHOT = "data/prices/person_scores_panel.csv"
# evidence_events window when collecting "active" filers: anyone who filed a purchase
# we saw in the last year is worth a track record.
ACTIVE_WINDOW_DAYS = 365


# "{filer_id}-{YYYY-MM-DD}-purchase" — the DATE itself contains dashes, so a naive
# rsplit corrupts the id (found via 13/13 failed fetches on the first live run).
_EVENT_KEY_FILER = re.compile(r"^(?P<fid>.+)-\d{4}-\d{2}-\d{2}-purchase$")


def _active_congress_filers(events_by_ticker: dict[str, list[dict]]) -> dict[str, str]:
    """filer_id -> display name for every congress purchase in the store.

    Older events (before details carried filer_id) fall back to parsing the event_key."""
    filers: dict[str, str] = {}
    for events in events_by_ticker.values():
        for event in events:
            if event["source"] != SOURCE_CONGRESS:
                continue
            details = event.get("details") or {}
            filer_id = details.get("filer_id")
            if not filer_id:
                match = _EVENT_KEY_FILER.match(event["event_key"])
                filer_id = match.group("fid") if match else None
            if filer_id and filer_id != "unknown":
                filers[filer_id] = details.get("politician") or filer_id
    return filers


def collect_calls(
    db_path: str,
    *,
    now: str,
    fetch_filer: Callable[[str], dict | None] = fetch_filer_history,
) -> tuple[list[Call], dict]:
    """All scoreable calls: mirror backfill per active filer + own-store fund/insider
    events. Insiders get NO backfill (unlike congress filers): Form 4 has no per-person
    full-history mirror, so their scores simply accumulate as our own ledger resolves
    events over time — same pattern as 13F funds already use."""
    events_by_ticker = events_in_window(
        db_path, window_days=ACTIVE_WINDOW_DAYS, now=now
    )
    filers = _active_congress_filers(events_by_ticker)
    calls: list[Call] = []
    counters = {"filers": len(filers), "filer_fetch_failed": 0, "backfill_calls": 0,
                "fund_calls": 0, "insider_calls": 0}
    for filer_id in sorted(filers):
        payload = fetch_filer(filer_id)
        if payload is None:
            counters["filer_fetch_failed"] += 1
            continue
        filer_calls, _ = calls_from_filer_payload(payload)
        counters["backfill_calls"] += len(filer_calls)
        calls.extend(filer_calls)
    own_events = [event for events in events_by_ticker.values() for event in events]
    fund_calls = calls_from_events([e for e in own_events if e["source"] == SOURCE_13F])
    insider_calls = calls_from_events([e for e in own_events if e["source"] == SOURCE_INSIDER])
    counters["fund_calls"] = len(fund_calls)
    counters["insider_calls"] = len(insider_calls)
    calls.extend(fund_calls)
    calls.extend(insider_calls)
    return calls, counters


def run_person_scores(
    db_path: str,
    *,
    now: str,
    fetch_prices: Callable[[list[str], str], PricePanel],
    fetch_filer: Callable[[str], dict | None] = fetch_filer_history,
    lookback_years: int = 3,
) -> dict:
    calls, counters = collect_calls(db_path, now=now, fetch_filer=fetch_filer)
    cutoff = (
        datetime.fromisoformat(now).replace(tzinfo=None)
        - timedelta(days=int(lookback_years * 365.25))
    ).date().isoformat()
    in_window = [c for c in calls if c.t0 >= cutoff]
    counters["too_old"] = len(calls) - len(in_window)
    if not in_window:
        return {"persons": 0, "calls": 0, **counters}
    tickers = sorted({yf_symbol(c.ticker) for c in in_window} | {BENCHMARK})
    panel = fetch_prices(tickers, cutoff)
    scores = score_persons(in_window, panel.closes, now=now, benchmark=BENCHMARK)
    save_person_scores(db_path, list(scores.values()), now=now)
    scoreable = sum(s.scoreable for s in scores.values())
    return {
        "persons": len(scores),
        "scoreable": scoreable,
        "calls": len(in_window),
        "tickers": len(tickers),
        **counters,
    }


def _fetch_price_panel(tickers: list[str], start: str) -> PricePanel:
    """Network default; column-wise history (no common-range trim: congress tickers are
    heterogeneous — one junk symbol or young IPO must not truncate everyone else)."""
    from equity_scout.data.etf_panel import load_price_history

    return load_price_history(tickers, start=start, snapshot=PERSONS_SNAPSHOT, refresh=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--lookback-years", type=int, default=3)
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # fetch_filer passed explicitly: module-level lookup at CALL time keeps the seam
    # monkeypatchable (a default parameter would freeze the original at import).
    result = run_person_scores(
        args.db, now=now, fetch_prices=_fetch_price_panel,
        fetch_filer=fetch_filer_history, lookback_years=args.lookback_years,
    )
    print(
        f"Personen bewertet: {result.get('persons', 0)}"
        f" (davon mit Score: {result.get('scoreable', 0)});"
        f" Calls: {result.get('calls', 0)} über {result.get('tickers', 0)} Ticker"
        f" ({result.get('backfill_calls', 0)} Backfill, {result.get('fund_calls', 0)} Fonds,"
        f" {result.get('insider_calls', 0)} Insider,"
        f" {result.get('too_old', 0)} zu alt,"
        f" {result.get('filer_fetch_failed', 0)} Filer-Fetches fehlgeschlagen)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
