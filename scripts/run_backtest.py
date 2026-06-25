"""CLI: backtest the v1 strategies over the ETF basket and print honest, after-cost metrics.

First run fetches the price panel from yfinance and snapshots it to data/prices/etf_panel.csv;
later runs reuse the snapshot (use --refresh to re-fetch). Prints a comparison table (all strategies
share one Deflated-Sharpe trial set) plus a cost-sensitivity sweep {0,5,10,20} bps per strategy.

PAPER / RESEARCH ONLY. No alpha promise — see the disclaimer.
"""
from __future__ import annotations

import argparse
from dataclasses import replace

from equity_scout.constants import DISCLAIMER
from equity_scout.data.etf_panel import load_etf_panel
from equity_scout.engine import run_backtest
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.metrics import compute_metrics, daily_returns, deflated_sharpe_ratio, periodic_sharpe
from equity_scout.strategies.registry import default_strategies

COST_SWEEP_BPS = (0.0, 5.0, 10.0, 20.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2007-01-01", help="Panel start date (first fetch only).")
    ap.add_argument("--cost-bps", type=float, default=10.0, help="Headline round-trip cost.")
    ap.add_argument("--rebalance", default="ME", help="Pandas offset alias (ME=month-end).")
    ap.add_argument("--refresh", action="store_true", help="Re-fetch the panel from yfinance.")
    args = ap.parse_args()

    panel = load_etf_panel(ETF_TICKERS, start=args.start, refresh=args.refresh)
    span = f"{panel.dates[0].date()} … {panel.dates[-1].date()} ({len(panel.dates)} days)"
    print(f"\nETF panel: {', '.join(panel.tickers)}\nSpan: {span}\n")

    strategies = default_strategies()
    results = [run_backtest(s, panel, rebalance=args.rebalance, costs_bps=args.cost_bps) for s in strategies]
    trial_sharpes = [periodic_sharpe(daily_returns(r.equity)) for r in results]

    header = f"{'Strategy':<22}{'CAGR':>8}{'Vol':>8}{'Sharpe':>8}{'Sortino':>9}{'MaxDD':>8}{'Calmar':>8}{'Turn/y':>8}{'DSR':>7}"
    print(f"After {args.cost_bps:.0f} bps round-trip costs:\n{header}\n{'-' * len(header)}")
    for result in results:
        m = compute_metrics(result.equity)
        m = replace(
            m,
            annual_turnover=result.annual_turnover,
            deflated_sharpe=deflated_sharpe_ratio(daily_returns(result.equity), trial_sharpes),
        )
        print(
            f"{result.strategy_name:<22}{m.cagr:>7.1%}{m.annual_volatility:>8.1%}{m.sharpe:>8.2f}"
            f"{m.sortino:>9.2f}{m.max_drawdown:>8.1%}{m.calmar:>8.2f}{m.annual_turnover:>8.2f}{m.deflated_sharpe:>7.2f}"
        )

    print("\nCost sensitivity (terminal value of 1.0, by round-trip bps):")
    print(f"{'Strategy':<22}" + "".join(f"{int(b):>9}bp" for b in COST_SWEEP_BPS))
    for strategy in strategies:
        cells = "".join(
            f"{run_backtest(strategy, panel, rebalance=args.rebalance, costs_bps=b).equity.iloc[-1]:>11.3f}"
            for b in COST_SWEEP_BPS
        )
        print(f"{strategy.name:<22}{cells}")

    print(f"\n{DISCLAIMER}\n")


if __name__ == "__main__":
    main()
