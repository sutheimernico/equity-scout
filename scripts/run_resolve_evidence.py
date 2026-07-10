"""Resolve due evidence-ledger rows against realized forward relative returns (vs SPY).

Mirror of scripts/run_resolve_predictions.py for the evidence ledger: for every
evidence event whose horizon has elapsed, fetch the REAL forward prices and fill the
outcome — never a back-filled guess. Measurement starts at the row's created_at (the
day the tool KNEW about the fact), so the measured edge is the edge a reader of the
alerts could actually have had — filings are already stale when they arrive.

Usage:
    python scripts/run_resolve_evidence.py [--db equity_scout.db]
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone

import pandas as pd

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.ledger import due_evidence, resolve_evidence, stats_by_source
from equity_scout.evidence.person_track import yf_symbol
from equity_scout.market import PricePanel
from equity_scout.ml.entry_eval import relative_forward_return

BENCHMARK = "SPY"
# Own snapshot: resolving must never clobber the training/backtest/prediction panels.
RESOLVE_SNAPSHOT = "data/prices/resolve_evidence_panel.csv"


def _as_of_timestamp(created_at: str) -> pd.Timestamp:
    ts = pd.Timestamp(created_at)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def _realized_relative_return(
    panel: PricePanel, ticker: str, created_at: str, horizon_days: int
) -> float | None:
    """Ticker-minus-SPY forward return over `horizon_days` trading days from the first
    panel date on/after created_at; None (row stays open) if the panel lacks the ticker
    or the full forward window."""
    closes = panel.closes
    symbol = yf_symbol(ticker)
    if symbol not in closes.columns or BENCHMARK not in closes.columns:
        return None
    pair = closes[[symbol, BENCHMARK]].dropna()
    on_or_after = pair.index[pair.index >= _as_of_timestamp(created_at)]
    if len(on_or_after) == 0:
        return None
    return relative_forward_return(
        pair[symbol], pair[BENCHMARK], on_or_after[0], horizon_days
    )


def run_resolve_evidence(
    db_path: str,
    *,
    now: str,
    fetch_prices: Callable[[list[str], str], PricePanel],
) -> dict:
    """Resolve every due evidence row. Returns {resolved, still_open}."""
    due = due_evidence(db_path, now)
    resolved = 0
    if due:
        tickers = sorted({yf_symbol(d["ticker"]) for d in due} | {BENCHMARK})
        start = min(_as_of_timestamp(d["created_at"]) for d in due).date().isoformat()
        panel = fetch_prices(tickers, start)
        for row in due:
            rel = _realized_relative_return(
                panel, row["ticker"], row["created_at"], row["horizon_days"]
            )
            if rel is None:
                continue  # forward window not yet fully observable — resolve later
            if resolve_evidence(
                db_path, row["id"], realized_relative_return=rel, resolved_at=now
            ):
                resolved += 1
    still_open = sum(entry["n_open"] for entry in stats_by_source(db_path).values())
    return {"resolved": resolved, "still_open": still_open}


def _fetch_price_panel(tickers: list[str], start: str) -> PricePanel:
    """Network default; column-wise history — evidence tickers are heterogeneous, so a
    junk symbol or young IPO must not trim every other ticker's usable range."""
    from equity_scout.data.etf_panel import load_price_history

    return load_price_history(tickers, start=start, snapshot=RESOLVE_SNAPSHOT, refresh=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_resolve_evidence(args.db, now=now, fetch_prices=_fetch_price_panel)
    print(
        f"Evidenz aufgelöst: {result['resolved']} Zeile(n);"
        f" noch offen: {result['still_open']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
