"""Forward paper trading: run a strategy *forward* in time as a persistent account.

The backtest (`engine.run_backtest`) replays a strategy over history. This module does the honest
inverse: a stateful `ForwardAccount` that is advanced one step at a time as new prices arrive, so a
real out-of-sample track record accumulates from today on. The strategy stays state-free — the same
`decide(as_of, market)` runs here as in the backtest; only the account carries state.

Each `advance_account` step: drift the held weights with the realised return since the last step
(same formula as the engine), let the strategy pick new targets from data up to today, charge cost on
the turnover, and emit a valuation snapshot. Advancing twice on the same panel date is a no-op
(idempotent), so a daily cron or a manual run is safe to repeat.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import Strategy, normalise_weights, turnover, weights_dict


@dataclass(frozen=True)
class ForwardAccount:
    """The accumulating state of one strategy run forward. `weights` are the post-rebalance targets
    set on `last_as_of`; they are drifted to the present at the next advance."""

    strategy_name: str
    initial_capital: float
    equity: float
    benchmark_ticker: str
    benchmark_equity: float
    last_as_of: str | None  # ISO date of the last advance; None until first advanced
    weights: dict[str, float] = field(default_factory=dict)

    @classmethod
    def fresh(
        cls,
        strategy_name: str,
        *,
        initial_capital: float = 10_000.0,
        benchmark_ticker: str = "SPY",
    ) -> ForwardAccount:
        return cls(
            strategy_name=strategy_name,
            initial_capital=initial_capital,
            equity=initial_capital,
            benchmark_ticker=benchmark_ticker,
            benchmark_equity=initial_capital,
            last_as_of=None,
            weights={},
        )


@dataclass(frozen=True)
class ForwardValuation:
    created_at: str  # ISO date (the panel date this snapshot is for)
    equity: float
    total_return: float
    benchmark_equity: float
    benchmark_return: float


def _price_on_or_before(series: pd.Series, date: pd.Timestamp) -> float | None:
    visible = series.loc[:date]
    return float(visible.iloc[-1]) if len(visible) else None


def _asset_return(closes: pd.DataFrame, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Total return of `ticker` from the close on/before `start` to the close on/before `end`."""
    if ticker not in closes.columns:
        return 0.0
    series = closes[ticker].dropna()
    p0 = _price_on_or_before(series, start)
    p1 = _price_on_or_before(series, end)
    if p0 is None or p1 is None or p0 <= 0:
        return 0.0
    return p1 / p0 - 1.0


def advance_account(
    account: ForwardAccount,
    strategy: Strategy,
    panel: PricePanel,
    *,
    costs_bps: float = 10.0,
) -> tuple[ForwardAccount, ForwardValuation | None]:
    """Advance `account` to the latest panel date. Returns (account, valuation); valuation is None
    when the account is already current for that date (idempotent)."""
    if len(panel.dates) == 0:
        return account, None
    today = panel.dates[-1]
    last = pd.Timestamp(account.last_as_of) if account.last_as_of else None
    if last is not None and last >= today:
        return account, None  # already current — no new trading day to book

    closes = panel.closes
    equity = account.equity
    benchmark_equity = account.benchmark_equity
    weights = dict(account.weights)

    # 1. Drift held weights + benchmark with the realised return since the last advance.
    if last is not None:
        port_return = sum(w * _asset_return(closes, t, last, today) for t, w in weights.items())
        equity *= 1.0 + port_return
        growth = 1.0 + port_return
        if growth > 0 and weights:
            weights = {
                t: w * (1.0 + _asset_return(closes, t, last, today)) / growth
                for t, w in weights.items()
            }
        benchmark_equity *= 1.0 + _asset_return(closes, account.benchmark_ticker, last, today)

    # 2. Strategy decides new targets from data up to and including today.
    view = MarketView(panel, today + pd.Timedelta(days=1))
    targets = weights_dict(normalise_weights(strategy.decide(view.as_of, view)))

    # 3. Charge cost on the rebalance turnover (same convention as the engine).
    equity *= 1.0 - turnover(weights, targets) * costs_bps / 10_000.0

    new_account = replace(
        account,
        equity=equity,
        benchmark_equity=benchmark_equity,
        last_as_of=today.date().isoformat(),
        weights=targets,
    )
    valuation = ForwardValuation(
        created_at=today.date().isoformat(),
        equity=equity,
        total_return=equity / account.initial_capital - 1.0,
        benchmark_equity=benchmark_equity,
        benchmark_return=benchmark_equity / account.initial_capital - 1.0,
    )
    return new_account, valuation
