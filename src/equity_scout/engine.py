"""Backtest engine: turn a strategy's target weights into a total-return equity curve.

Weight-based (not share-based): between rebalances the weights drift with asset returns; on a
rebalance date the strategy's `decide` (fed a look-ahead-safe view) sets new targets and we charge a
cost on the turnover (sum of absolute weight changes). Equity is a total-return index starting at 1.

**No look-ahead by construction:** the decision on date `t` sees `MarketView(panel, t)`, which
exposes only prices strictly before `t`; the new weights then earn the return from `t` onward. The
same `decide` runs here and in forward paper trading — backtest is just the engine over history.

Cost convention: `cost_bps` is charged per unit of *one-way* turnover (Σ|Δweight|), so the initial
build-up of a 100%-invested book costs `cost_bps` once. Default 10 bps is retail-ETF realistic; the
CLI sweeps {0,5,10,20} to show the turnover lever honestly.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import AccountState, Strategy, clip_weights

_TURNOVER_EPS = 1e-9


@dataclass(frozen=True)
class Trade:
    date: str  # ISO date
    weights: dict[str, float]  # target weights set on this date
    turnover: float


@dataclass(frozen=True)
class BacktestResult:
    strategy_name: str
    equity: pd.Series  # total-return index, starts at 1.0
    trades: list[Trade]
    total_turnover: float
    cost_bps: float

    @property
    def years(self) -> float:
        return max(len(self.equity) / 252.0, 1e-9)

    @property
    def annual_turnover(self) -> float:
        return self.total_turnover / self.years


def _turnover(old: dict[str, float], new: dict[str, float]) -> float:
    return sum(abs(new.get(t, 0.0) - old.get(t, 0.0)) for t in set(old) | set(new))


def run_backtest(
    strategy: Strategy,
    panel: PricePanel,
    *,
    rebalance: str = "ME",
    cost_bps: float = 10.0,
) -> BacktestResult:
    returns = panel.closes.pct_change()
    rebalance_dates = set(panel.rebalance_dates(rebalance))
    cost_rate = cost_bps / 10_000.0

    weights: dict[str, float] = {}  # current invested weights; remainder is cash (return 0)
    equity = 1.0
    equity_values: list[float] = []
    trades: list[Trade] = []
    total_turnover = 0.0
    step = 0

    for i, date in enumerate(panel.dates):
        if i > 0 and weights:
            row = returns.loc[date].fillna(0.0)  # a missing day = price unchanged
            port_return = sum(w * float(row[ticker]) for ticker, w in weights.items())
            equity *= 1.0 + port_return
            growth = 1.0 + port_return
            if growth > 0:  # drift weights with realised returns
                weights = {
                    ticker: w * (1.0 + float(row[ticker])) / growth for ticker, w in weights.items()
                }

        if date in rebalance_dates:
            view = MarketView(panel, date)
            if view.has_data:
                target = clip_weights(strategy.decide(date, view, AccountState(dict(weights), step)))
                turnover = _turnover(weights, target)
                equity *= 1.0 - turnover * cost_rate
                total_turnover += turnover
                if turnover > _TURNOVER_EPS:
                    trades.append(Trade(date.date().isoformat(), target, turnover))
                weights = target
                step += 1

        equity_values.append(equity)

    return BacktestResult(
        strategy_name=strategy.name,
        equity=pd.Series(equity_values, index=panel.dates),
        trades=trades,
        total_turnover=total_turnover,
        cost_bps=cost_bps,
    )
