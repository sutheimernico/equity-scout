"""Advance the paper portfolio against the latest run's picks. PAPER ONLY — no real orders.

Reads the most recent funnel run, fetches current prices for held + candidate tickers (and the
benchmark), buys fresh picks above the threshold (buy-and-hold), and records a valuation snapshot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.data.fake_provider import FakeProvider
from equity_scout.data.yf_provider import YFinanceProvider
from equity_scout.models import Instrument
from equity_scout.portfolio import advance, mark_to_market, new_portfolio
from equity_scout.portfolio_storage import (
    append_valuation,
    init_portfolio_db,
    load_portfolio,
    save_portfolio,
)
from equity_scout.storage import load_latest_run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB_PATH)
    ap.add_argument("--bucket", default="balanced", help="Which bucket's picks to buy from.")
    ap.add_argument("--threshold", type=float, default=0.70)
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--provider", choices=["fake", "yfinance"], default="yfinance")
    args = ap.parse_args()

    run = load_latest_run(args.db)
    if run is None:
        print("No funnel run found — run scripts/run_scout.py first.")
        return

    picks = run.buckets.get(args.bucket, [])
    init_portfolio_db(args.db)
    portfolio = load_portfolio(args.db) or new_portfolio(args.capital)
    provider = YFinanceProvider() if args.provider == "yfinance" else FakeProvider()

    # Need prices for held positions + candidate picks (held may have dropped out of the picks).
    needed: dict[str, Instrument] = {t: p.instrument for t, p in portfolio.positions.items()}
    needed.update({p.instrument.ticker: p.instrument for p in picks})
    prices = {t: q.price for t, inst in needed.items() if (q := provider.fetch_quote(inst)).price}

    bench = Instrument(portfolio.benchmark_ticker, portfolio.benchmark_ticker,
                       "US", "US", "USD", "ETF")
    benchmark_price = provider.fetch_quote(bench).price

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    portfolio, trades = advance(portfolio, picks, prices, now=now,
                                threshold=args.threshold, benchmark_price=benchmark_price)
    save_portfolio(args.db, portfolio)
    valuation = mark_to_market(portfolio, prices, benchmark_price=benchmark_price)
    append_valuation(args.db, now, valuation)

    for trade in trades:
        print(trade)
    print(
        f"\nPaper portfolio: {valuation.total_value:,.0f} "
        f"({valuation.total_return * 100:+.1f}%) vs benchmark {valuation.benchmark_return * 100:+.1f}% "
        f"| {valuation.open_positions} positions | cash {valuation.cash:,.0f}"
    )
    print("PAPER ONLY — forward test of whether high-composite picks pay off. No real orders.")


if __name__ == "__main__":
    main()
