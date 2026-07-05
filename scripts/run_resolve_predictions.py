"""Resolve due entry predictions against realized forward relative returns (ticker vs SPY).

The honesty loop's second half (invariant #3): for every prediction whose horizon has elapsed,
fetch the REAL forward prices and fill the outcome — never a back-filled guess. A prediction whose
full forward horizon is not yet observable in the fetched panel is left open, to be resolved later.
Network is isolated behind the `fetch_prices` seam / the module-level `_fetch_price_panel` loader so
tests run offline; `now` is injected (datetime.now only in main()).

Usage:
    python scripts/run_resolve_predictions.py [--db equity_scout.db]
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone

import pandas as pd

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.market import PricePanel
from equity_scout.ml.entry_eval import relative_forward_return
from equity_scout.ml.prediction_ledger import (
    due_predictions,
    resolve_prediction,
    resolved_stats,
)

BENCHMARK = "SPY"
# Distinct snapshot so resolving never clobbers the training/backtest panels.
RESOLVE_SNAPSHOT = "data/prices/resolve_panel.csv"


def _as_of_timestamp(created_at: str) -> pd.Timestamp:
    """A prediction's creation time (tz-aware ISO) as a tz-naive date, to match the panel index."""
    ts = pd.Timestamp(created_at)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def _realized_relative_return(
    panel: PricePanel, ticker: str, created_at: str, horizon_days: int
) -> float | None:
    """Realized forward return of `ticker` minus SPY over `horizon_days` trading days, measured from
    the first panel date on/after the prediction's creation date. Both legs share the benchmark's
    aligned calendar. None if the panel lacks the ticker or a full forward horizon (→ stays open)."""
    closes = panel.closes
    if ticker not in closes.columns or BENCHMARK not in closes.columns:
        return None
    pair = closes[[ticker, BENCHMARK]].dropna()
    on_or_after = pair.index[pair.index >= _as_of_timestamp(created_at)]
    if len(on_or_after) == 0:
        return None
    at = on_or_after[0]
    return relative_forward_return(pair[ticker], pair[BENCHMARK], at, horizon_days)


def run_resolve_predictions(
    db_path: str,
    *,
    now: str,
    fetch_prices: Callable[[list[str], str], PricePanel],
) -> dict:
    """Resolve every due prediction against its realized forward relative return. Returns
    {resolved, still_open}. still_open counts all predictions left open after this run — those not
    yet due, plus any due one whose forward window is not yet fully observable."""
    due = due_predictions(db_path, now)
    resolved = 0
    if due:
        tickers = sorted({d["ticker"] for d in due} | {BENCHMARK})
        start = min(_as_of_timestamp(d["created_at"]) for d in due).date().isoformat()
        panel = fetch_prices(tickers, start)
        for pred in due:
            rel = _realized_relative_return(
                panel, pred["ticker"], pred["created_at"], pred["horizon_days"]
            )
            if rel is None:
                continue  # forward window not yet fully observable — resolve honestly later
            if resolve_prediction(
                db_path, pred["id"], realized_relative_return=rel, resolved_at=now
            ):
                resolved += 1
    return {"resolved": resolved, "still_open": resolved_stats(db_path)["n_open"]}


def _fetch_price_panel(tickers: list[str], start: str) -> PricePanel:
    """Network default: fresh daily closes for the due tickers + SPY from `start`. refresh=True so
    the forward window reflects the latest prices; a distinct snapshot keeps other panels untouched.
    Lazy import keeps the network out of import time and tests."""
    from equity_scout.data.etf_panel import load_etf_panel

    return load_etf_panel(tickers, start=start, snapshot=RESOLVE_SNAPSHOT, refresh=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_resolve_predictions(args.db, now=now, fetch_prices=_fetch_price_panel)
    print(f"Aufgelöst: {result['resolved']} Vorhersage(n); noch offen: {result['still_open']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
