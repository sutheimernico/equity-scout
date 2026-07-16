"""Queue + resolve the event-reaction study (Strang B4): honest measurement of the
paper reaction (beat -> long, miss -> hypothetical short) to already-classified
beat/miss/guidance events (Strang B3), over 1d/5d trading days from daily closes.

Two steps, both idempotent:
  1. Queue a `pending` row for every classified event with a direction that isn't
     queued yet (`event_reactions.queue_pending_reactions`).
  2. Resolve every pending row whose 5d window has fully elapsed against the REAL
     forward daily closes — never a back-filled guess. A row whose window has not
     elapsed yet, or whose ticker never turns up in the fetched panel, stays pending
     and is picked up again next run.

1h is never attempted here — see `evidence/event_reactions.py`'s module docstring;
it has no historical intraday data to resolve against at all.

Network is isolated behind the `fetch_prices` seam / the module-level
`_fetch_price_panel` loader (same idiom as run_resolve_predictions.py /
run_resolve_evidence.py), so tests run offline. Unlike those two, there is no
wall-clock `now` here at all: due-ness is not a calendar check against a stored
`resolve_after` date, it is "does the fetched panel actually reach 5 trading days
past seen_at" — a question `compute_reaction_returns` already answers from the
data itself, so a redundant calendar gate would only approximate what the real
check already does exactly.

Usage:
    python scripts/run_resolve_events.py [--db equity_scout.db]
"""
from __future__ import annotations

import argparse
from collections.abc import Callable

import pandas as pd

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.event_reactions import (
    compute_reaction_returns,
    pending_reactions,
    queue_pending_reactions,
    resolve_reaction,
)
from equity_scout.evidence.event_storage import load_classified_events
from equity_scout.market import PricePanel

# Distinct snapshot so resolving never clobbers the training/backtest/other-resolve panels.
RESOLVE_SNAPSHOT = "data/prices/resolve_events_panel.csv"


def _as_of_timestamp(seen_at: str) -> pd.Timestamp:
    ts = pd.Timestamp(seen_at)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def run_resolve_events(
    db_path: str,
    *,
    fetch_prices: Callable[[list[str], str], PricePanel],
) -> dict:
    """Queue newly classified directional events, then resolve every pending row
    whose 5d window is now fully observable. Returns {resolved, still_pending}."""
    queue_pending_reactions(db_path, load_classified_events(db_path))

    pending = pending_reactions(db_path)
    resolved = 0
    if pending:
        tickers = sorted({row["ticker"] for row in pending})
        start = min(_as_of_timestamp(row["seen_at"]) for row in pending).date().isoformat()
        panel = fetch_prices(tickers, start)
        for row in pending:
            if row["ticker"] not in panel.closes.columns:
                continue
            result = compute_reaction_returns(
                panel.closes[row["ticker"]], row["seen_at"], row["event_type"]
            )
            if result["status"] != "resolved":
                continue  # 5d window not yet fully observable — resolve honestly later
            if resolve_reaction(
                db_path, row["event_key"], ret_1d=result["ret_1d"], ret_5d=result["ret_5d"]
            ):
                resolved += 1

    return {"resolved": resolved, "still_pending": len(pending_reactions(db_path))}


def _fetch_price_panel(tickers: list[str], start: str) -> PricePanel:
    """Network default: fresh daily closes for the pending tickers from `start`.
    Column-wise (load_price_history, not load_etf_panel): event tickers are
    heterogeneous, so one junk symbol or young IPO must not trim every other
    ticker's usable range. Lazy import keeps the network out of import time/tests."""
    from equity_scout.data.etf_panel import load_price_history

    return load_price_history(tickers, start=start, snapshot=RESOLVE_SNAPSHOT, refresh=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    result = run_resolve_events(args.db, fetch_prices=_fetch_price_panel)
    print(
        f"Event-Reaktionen aufgelöst: {result['resolved']}; noch pending: {result['still_pending']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
