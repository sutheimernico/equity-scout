"""Earnings-calendar CLI: refresh yfinance earnings dates for every ticker we currently
track (watchlist + main portfolio + both arena lanes) and persist them.

Usage:
    python scripts/run_earnings.py [--db equity_scout.db]

Thin glue over already-tested building blocks: tracked_tickers.tracked_tickers picks the
ticker set, data.yf_provider.fetch_earnings_dates does the (injectable) fetch,
earnings_storage persists it. Run this once a day (wired into daily_copilot.sh, ahead of
the digest) — earnings dates rarely change within a day, so the 15-min intraday cadence
is not needed here.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.data.yf_provider import fetch_earnings_dates
from equity_scout.earnings_storage import save_earnings_dates
from equity_scout.tracked_tickers import tracked_tickers


def run_earnings(
    db_path: str,
    tickers: set[str],
    *,
    fetched_on: str,
    fetch: Callable[[str], list[str]] | None = None,
) -> int:
    """Fetch + persist earnings dates for every ticker in ``tickers``.

    Returns how many tickers had at least one known upcoming date this run (an honest
    coverage count, not a promise — many non-US tickers have none). ``fetch`` resolved at
    call time (not a bound default), same pattern as run_radar.fetch_history, so tests can
    monkeypatch the module-level ``fetch_earnings_dates`` and have it take effect.
    """
    if fetch is None:
        fetch = fetch_earnings_dates
    known = 0
    for ticker in sorted(tickers):
        dates = fetch(ticker)
        if dates:
            known += 1
        save_earnings_dates(db_path, ticker, dates, fetched_on=fetched_on)
    return known


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    tickers = tracked_tickers(args.db)
    if not tickers:
        print("Keine Watchlist-/Depot-Ticker gefunden — nichts zu aktualisieren.")
        return 0

    fetched_on = datetime.now(timezone.utc).isoformat(timespec="seconds")
    known = run_earnings(args.db, tickers, fetched_on=fetched_on)
    print(f"Earnings-Kalender aktualisiert: {known}/{len(tickers)} Ticker mit bekanntem Termin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
