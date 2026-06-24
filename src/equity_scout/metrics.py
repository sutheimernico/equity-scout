"""Honest performance metrics for an equity curve.

Implemented in-house (no metrics lib): the standard ratios are a few lines, and the Deflated Sharpe
Ratio — the one that matters most here — has no maintained free library anyway. The Normal CDF comes
from the stdlib (`statistics.NormalDist`), so there is no scipy/empyrical dependency.

The non-negotiable one is the **Deflated Sharpe Ratio** (Bailey & López de Prado 2014): with enough
strategies/configs tried, noise alone produces a high Sharpe, so a raw Sharpe overstates skill. DSR
asks "given N trials, is this Sharpe beyond what the best of N random tries would show?" and corrects
for skew/kurtosis. We test several strategies + an ML model, so raw Sharpe is systematically inflated.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import pandas as pd

TRADING_DAYS_PER_YEAR = 252
_EULER_MASCHERONI = 0.5772156649015329
_NORMAL = NormalDist()


@dataclass(frozen=True)
class PerformanceMetrics:
    cagr: float
    annual_volatility: float
    sharpe: float  # annualised
    sortino: float  # annualised
    max_drawdown: float  # negative
    calmar: float
    # filled in by the comparison layer (need turnover / the full set of trials):
    annual_turnover: float | None = None
    deflated_sharpe: float | None = None


def daily_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def cagr(equity: pd.Series) -> float:
    """Compound annual growth, trading-day-based (252/periods) so it is calendar-independent."""
    periods = len(equity) - 1
    if periods <= 0 or equity.iloc[0] <= 0:
        return 0.0
    growth = equity.iloc[-1] / equity.iloc[0]
    if growth <= 0:
        return -1.0
    return float(growth ** (TRADING_DAYS_PER_YEAR / periods) - 1.0)


def annual_volatility(returns: pd.Series) -> float:
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))


def sharpe(returns: pd.Series, risk_free_daily: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_daily
    sd = excess.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(excess.mean() / sd * math.sqrt(TRADING_DAYS_PER_YEAR))


def sortino(returns: pd.Series, target_daily: float = 0.0) -> float:
    """Like Sharpe but penalises only downside. Above-target returns are set to 0 (not dropped)."""
    if len(returns) < 2:
        return 0.0
    downside = (returns - target_daily).clip(upper=0.0)
    downside_dev = math.sqrt((downside**2).mean())
    if downside_dev == 0:
        return 0.0
    return float((returns.mean() - target_daily) / downside_dev * math.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown(equity: pd.Series) -> float:
    """Largest peak-to-trough decline, as a negative fraction."""
    running_max = equity.cummax()
    drawdowns = equity / running_max - 1.0
    return float(drawdowns.min())


def calmar(equity: pd.Series) -> float:
    mdd = max_drawdown(equity)
    if mdd == 0:
        return 0.0
    return float(cagr(equity) / abs(mdd))


def periodic_sharpe(returns: pd.Series) -> float:
    """Non-annualised Sharpe (per observation) — the form the PSR/DSR formulas expect."""
    sd = returns.std(ddof=1)
    return 0.0 if sd == 0 else float(returns.mean() / sd)


def psr_from_stats(
    sharpe_periodic: float, n_obs: int, skew: float, kurtosis: float, benchmark: float = 0.0
) -> float:
    """Probabilistic Sharpe from compact stats (no return series needed) — lets the research ledger
    store 4 numbers per trial and recompute DSR as the trial count grows."""
    if n_obs < 3:
        return 0.5
    denom = math.sqrt(max(1e-12, 1.0 - skew * sharpe_periodic + (kurtosis - 1.0) / 4.0 * sharpe_periodic**2))
    z = (sharpe_periodic - benchmark) * math.sqrt(n_obs - 1) / denom
    return float(_NORMAL.cdf(z))


def probabilistic_sharpe_ratio(returns: pd.Series, benchmark_periodic_sharpe: float = 0.0) -> float:
    """P(true Sharpe > benchmark), correcting for sample length, skew and kurtosis (Bailey & LdP)."""
    if len(returns) < 3:
        return 0.5
    # pandas reports excess kurtosis; the formula wants raw (+3)
    return psr_from_stats(
        periodic_sharpe(returns), len(returns), float(returns.skew()), float(returns.kurt()) + 3.0,
        benchmark_periodic_sharpe,
    )


def expected_max_sharpe(trial_periodic_sharpes: list[float]) -> float:
    """The Sharpe the best of N independent trials would show by chance (the DSR deflation term).
    Rises with the number of trials — this is the built-in overfitting budget."""
    n_trials = len(trial_periodic_sharpes)
    if n_trials <= 1:
        return 0.0
    sr_variance = float(pd.Series(trial_periodic_sharpes).var(ddof=1))
    if sr_variance <= 0:
        return 0.0
    return math.sqrt(sr_variance) * (
        (1.0 - _EULER_MASCHERONI) * _NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
        + _EULER_MASCHERONI * _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    )


def deflated_sharpe_ratio(returns: pd.Series, trial_periodic_sharpes: list[float]) -> float:
    """DSR: PSR against the Sharpe the best of N independent trials would show by chance.
    With a single trial it degenerates to PSR against 0."""
    return probabilistic_sharpe_ratio(returns, expected_max_sharpe(trial_periodic_sharpes))


def compute_metrics(equity: pd.Series) -> PerformanceMetrics:
    """Return-curve metrics (turnover and DSR are attached later by the comparison layer)."""
    rets = daily_returns(equity)
    return PerformanceMetrics(
        cagr=cagr(equity),
        annual_volatility=annual_volatility(rets),
        sharpe=sharpe(rets),
        sortino=sortino(rets),
        max_drawdown=max_drawdown(equity),
        calmar=calmar(equity),
    )
