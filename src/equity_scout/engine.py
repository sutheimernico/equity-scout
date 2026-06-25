"""Backtest engine: turn a strategy's target weights into a total-return equity curve.

Weight-based (not share-based): between rebalances the weights drift with asset returns; on a
rebalance date the strategy's `decide` (fed a look-ahead-safe view) sets new targets and we charge a
cost on the turnover (sum of absolute weight changes). Equity is a total-return index starting at
`initial_capital` (default 1.0, i.e. growth-of-1).

**No look-ahead by construction:** the decision on date `t` sees `MarketView(panel, t)`, which
exposes only prices strictly before `t`; the new weights then earn the return from `t` onward. The
same `decide` runs here and in forward paper trading — backtest is just the engine over history.

Cost convention: `costs_bps` is charged per unit of *one-way* turnover (Σ|Δweight|), so the initial
build-up of a 100%-invested book costs `costs_bps` once. Default 10 bps is retail-ETF realistic; the
CLI sweeps {0,5,10,20} to show the turnover lever honestly.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import Strategy, normalise_weights, turnover, weights_dict

_TURNOVER_EPS = 1e-9
TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class Trade:
    date: str  # ISO date
    weights: dict[str, float]  # target weights set on this date
    turnover: float


@dataclass(frozen=True)
class BacktestResult:
    strategy_name: str
    equity: pd.Series  # total-return index, starts at `initial_capital`
    trades: list[Trade]
    total_turnover: float
    costs_bps: float
    weights_by_date: pd.DataFrame  # post-rebalance target weights, index = rebalance dates
    sweep_terminals: dict[float, float] = field(default_factory=dict)  # bps -> terminal value

    @property
    def years(self) -> float:
        return max(len(self.equity) / TRADING_DAYS_PER_YEAR, 1e-9)

    @property
    def annual_turnover(self) -> float:
        return self.total_turnover / self.years


def run_backtest(
    strategy: Strategy,
    panel: PricePanel,
    *,
    rebalance: str = "ME",
    costs_bps: float = 10.0,
    initial_capital: float = 1.0,
    sweep_bps: tuple[float, ...] = (),
) -> BacktestResult:
    # Vectorised once into a numpy array so the daily drift loop avoids per-day pandas label lookups
    # (the hot path: ~5000 days). A missing day = price unchanged (return 0).
    returns_values = np.nan_to_num(panel.closes.pct_change().to_numpy(), nan=0.0)
    col = {ticker: j for j, ticker in enumerate(panel.closes.columns)}
    rebalance_dates = set(panel.rebalance_dates(rebalance))
    cost_rate = costs_bps / 10_000.0

    weights: dict[str, float] = {}  # current invested weights; remainder is cash (return 0)
    equity = initial_capital
    equity_values: list[float] = []
    trades: list[Trade] = []
    weight_rows: dict[pd.Timestamp, dict[str, float]] = {}
    total_turnover = 0.0
    # Same strategy decisions, different cost levels — tracked in this one pass instead of re-running
    # the whole backtest per bps (the decide/MarketView work is the expensive part).
    sweep_equity = {bps: initial_capital for bps in sweep_bps}

    for i, date in enumerate(panel.dates):
        if i > 0 and weights:
            row = returns_values[i]
            port_return = sum(w * row[col[ticker]] for ticker, w in weights.items())
            equity *= 1.0 + port_return
            for bps in sweep_bps:
                sweep_equity[bps] *= 1.0 + port_return
            growth = 1.0 + port_return
            if growth > 0:  # drift weights with realised returns
                weights = {
                    ticker: w * (1.0 + row[col[ticker]]) / growth for ticker, w in weights.items()
                }

        if date in rebalance_dates:
            view = MarketView(panel, date)
            if view.has_data:
                target = weights_dict(normalise_weights(strategy.decide(date, view)))
                trade_turnover = turnover(weights, target)
                equity *= 1.0 - trade_turnover * cost_rate
                for bps in sweep_bps:
                    sweep_equity[bps] *= 1.0 - trade_turnover * bps / 10_000.0
                total_turnover += trade_turnover
                if trade_turnover > _TURNOVER_EPS:
                    trades.append(Trade(date.date().isoformat(), target, trade_turnover))
                weights = target
                weight_rows[date] = target

        equity_values.append(equity)

    return BacktestResult(
        strategy_name=strategy.name,
        equity=pd.Series(equity_values, index=panel.dates),
        trades=trades,
        total_turnover=total_turnover,
        costs_bps=costs_bps,
        weights_by_date=pd.DataFrame(weight_rows).T.fillna(0.0).sort_index(),
        sweep_terminals={bps: sweep_equity[bps] for bps in sweep_bps},
    )
