"""Build dashboard-ready reports for every strategy from one price panel.

`build_reports` is pure (panel in, reports out) so it is unit-testable on a synthetic panel; the API
wraps it in a cache. Each report carries the metrics (incl. Deflated Sharpe over the shared trial
set), a downsampled equity curve vs the 60/40 benchmark, current target weights, recent trades, and
the per-strategy cost-sensitivity sweep — everything a strategy tab needs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

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
from equity_scout.ml.attribution import attribution_summary
from equity_scout.ml.meta_model import DEFAULT_CONFIG, MetaConfig, run_meta_model
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
    # one backtest per strategy, computing the cost sweep in the same pass
    results = [run_backtest(s, panel, costs_bps=costs_bps, sweep_bps=COST_SWEEP_BPS) for s in strategies]
    trial_sharpes = [periodic_sharpe(daily_returns(r.equity)) for r in results]
    benchmark = next((r for r in results if r.strategy_name == BENCHMARK_NAME), results[0])
    benchmark_curve = _downsample(benchmark.equity)

    reports: list[StrategyReport] = []
    for result in results:
        returns = daily_returns(result.equity)
        metrics = replace(
            compute_metrics(result.equity),
            annual_turnover=result.annual_turnover,
            deflated_sharpe=deflated_sharpe_ratio(returns, trial_sharpes),
        )
        sweep = [[bps, round(float(result.sweep_terminals[bps]), 4)] for bps in COST_SWEEP_BPS]
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


@dataclass(frozen=True)
class MLReport:
    trained: bool
    metrics: PerformanceMetrics | None
    equity: list[list]  # OOS, from the first live bet, re-based to 1.0
    benchmark_equity: list[list]  # SPY buy-and-hold over the same OOS span
    n_bets: int
    oos_hit_rate: float
    avg_probability: float
    avg_exposure: float
    feature_importance: dict[str, float]
    attribution: dict = field(default_factory=dict)


def build_ml_report(
    panel: PricePanel, config: MetaConfig | None = None, *, risk: str = "SPY", costs_bps: float = 10.0
) -> MLReport:
    """Run the meta-model and shape it for the dashboard. The equity curve starts at the first
    out-of-sample bet (the early years are training-only) and is benchmarked against buy-and-hold of
    the risk asset — the honest question being whether the timing helps versus just holding it.
    `config` defaults to the fixed baseline; the API passes the research loop's current champion
    when one has been found, so the tab reflects what the search has actually learned."""
    result = run_meta_model(panel, config or DEFAULT_CONFIG, risk=risk, costs_bps=costs_bps)
    if not result.trained:
        return MLReport(False, None, [], [], 0, 0.0, 0.0, 0.0, {})

    active = result.exposure[result.exposure > 0]
    start = active.index[0] if not active.empty else result.equity.index[0]
    equity_oos = result.equity.loc[start:]
    equity_oos = equity_oos / equity_oos.iloc[0]
    spy = panel.closes[risk].loc[start:]
    spy = spy / spy.iloc[0]

    return MLReport(
        trained=True,
        metrics=compute_metrics(equity_oos),
        equity=_downsample(equity_oos),
        benchmark_equity=_downsample(spy),
        n_bets=result.n_bets,
        oos_hit_rate=round(result.oos_hit_rate, 3),
        avg_probability=round(result.avg_probability, 3),
        avg_exposure=round(float(result.exposure.loc[start:].mean()), 3),
        feature_importance=result.feature_importance,
        attribution=attribution_summary(result.bets),
    )
