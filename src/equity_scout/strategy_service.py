"""Build dashboard-ready reports for every strategy from one price panel.

`build_reports` is pure (panel in, reports out) so it is unit-testable on a synthetic panel; the API
wraps it in a cache. Each report carries the metrics (incl. Deflated Sharpe over the shared trial
set), a downsampled equity curve vs the 60/40 benchmark, current target weights, recent trades, and
the per-strategy cost-sensitivity sweep — everything a strategy tab needs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from equity_scout.engine import Trade, run_backtest
from equity_scout.market import PricePanel
from equity_scout.metrics import (
    PerformanceMetrics,
    compute_metrics,
    daily_returns,
    deflated_sharpe_ratio,
    periodic_sharpe,
)
from equity_scout.strategies.registry import default_strategies

COST_SWEEP_BPS = (0.0, 5.0, 10.0, 20.0)
BENCHMARK_NAME = "60/40"


@dataclass(frozen=True)
class StrategyReport:
    name: str
    is_benchmark: bool
    metrics: PerformanceMetrics
    equity: list[list]  # [[iso_date, value], ...] downsampled total-return index (starts at 1.0)
    benchmark_equity: list[list]  # 60/40 over the same dates
    current_weights: dict[str, float]  # latest target allocation, ticker -> weight
    recent_trades: list[Trade]
    cost_sweep: list[list]  # [[bps, terminal_value], ...]


def _downsample(equity: pd.Series, freq: str = "ME") -> list[list]:
    """Month-end sample (≈230 points over 19y) — enough for a chart, light over the wire. The very
    first day is prepended so the curve starts at the baseline (1.0) instead of after month one."""
    sampled = equity.resample(freq).last().dropna()
    points = [[date.date().isoformat(), round(float(value), 5)] for date, value in sampled.items()]
    start = [equity.index[0].date().isoformat(), round(float(equity.iloc[0]), 5)]
    if not points or points[0][0] != start[0]:
        points.insert(0, start)
    return points


def _latest_weights(weights_by_date: pd.DataFrame) -> dict[str, float]:
    if weights_by_date.empty:
        return {}
    last = weights_by_date.iloc[-1]
    return {ticker: round(float(w), 4) for ticker, w in last.items() if w > 1e-9}


def build_reports(panel: PricePanel, *, costs_bps: float = 10.0) -> list[StrategyReport]:
    strategies = default_strategies()
    results = [run_backtest(s, panel, costs_bps=costs_bps) for s in strategies]
    trial_sharpes = [periodic_sharpe(daily_returns(r.equity)) for r in results]
    benchmark = next((r for r in results if r.strategy_name == BENCHMARK_NAME), results[0])
    benchmark_curve = _downsample(benchmark.equity)

    reports: list[StrategyReport] = []
    for strategy, result in zip(strategies, results):
        returns = daily_returns(result.equity)
        metrics = replace(
            compute_metrics(result.equity),
            annual_turnover=result.annual_turnover,
            deflated_sharpe=deflated_sharpe_ratio(returns, trial_sharpes),
        )
        sweep = [
            [bps, round(float(run_backtest(strategy, panel, costs_bps=bps).equity.iloc[-1]), 4)]
            for bps in COST_SWEEP_BPS
        ]
        reports.append(
            StrategyReport(
                name=result.strategy_name,
                is_benchmark=result.strategy_name == BENCHMARK_NAME,
                metrics=metrics,
                equity=_downsample(result.equity),
                benchmark_equity=benchmark_curve,
                current_weights=_latest_weights(result.weights_by_date),
                recent_trades=result.trades[-12:],
                cost_sweep=sweep,
            )
        )
    return reports
