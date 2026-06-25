"""CLI: advance the forward paper accounts one step on the latest prices.

Each v1 strategy runs forward as its own persistent account. Run this (e.g. daily, or via cron) to
roll every account to the newest price and append a valuation snapshot — the forward, out-of-sample
track record that accumulates over real time. Idempotent: running twice on the same day books nothing
new (the valuation is unique per strategy + date).

PAPER / RESEARCH ONLY. No alpha promise — see the disclaimer.
"""
from __future__ import annotations

import argparse

from equity_scout.constants import DEFAULT_FORWARD_DB_PATH, DISCLAIMER
from equity_scout.data.etf_panel import load_etf_panel
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.forward_paper import ForwardAccount, advance_account
from equity_scout.forward_storage import append_valuation, init_forward_db, load_account, save_account
from equity_scout.strategies.registry import default_strategies


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_FORWARD_DB_PATH, help="Forward paper DB path.")
    ap.add_argument("--start", default="2007-01-01", help="Panel start date (first fetch only).")
    ap.add_argument("--cost-bps", type=float, default=10.0, help="Round-trip rebalance cost.")
    ap.add_argument("--refresh", action="store_true", help="Re-fetch the latest prices from yfinance.")
    args = ap.parse_args()

    panel = load_etf_panel(ETF_TICKERS, start=args.start, refresh=args.refresh)
    as_of = panel.dates[-1].date()
    print(f"\nForward paper — advancing to {as_of} ({len(panel.dates)} panel days)\n")

    init_forward_db(args.db)
    header = f"{'Strategy':<22}{'Equity':>12}{'Return':>9}{'Bench':>9}{'Status':>10}"
    print(f"{header}\n{'-' * len(header)}")
    for strategy in default_strategies():
        account = load_account(args.db, strategy.name) or ForwardAccount.fresh(strategy.name)
        advanced, valuation = advance_account(account, strategy, panel, costs_bps=args.cost_bps)
        save_account(args.db, advanced, updated_at=as_of.isoformat())
        status = "current"
        if valuation is not None:
            append_valuation(args.db, strategy.name, valuation)
            status = "advanced"
        print(
            f"{strategy.name:<22}{advanced.equity:>12,.0f}"
            f"{advanced.equity / advanced.initial_capital - 1:>8.1%}"
            f"{advanced.benchmark_equity / advanced.initial_capital - 1:>8.1%}{status:>10}"
        )

    print(f"\n{DISCLAIMER}\n")


if __name__ == "__main__":
    main()
