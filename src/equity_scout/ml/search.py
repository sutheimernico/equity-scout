"""The search space the research loop explores, and how to evaluate one point in it.

`sample_config(i)` draws a configuration deterministically from the trial index (reproducible, and a
fresh process resumes exactly where it left off). `evaluate_config` runs the full purged walk-forward
and returns compact, out-of-sample stats — enough to recompute the Deflated Sharpe later as the trial
count grows, without storing every equity curve. Many dimensions (features × model × signal × labels)
is the point: breadth is what lets the DSR's rising hurdle separate skill from luck.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from equity_scout.market import PricePanel
from equity_scout.metrics import compute_metrics, daily_returns, periodic_sharpe
from equity_scout.ml.features import FEATURE_NAMES
from equity_scout.ml.fred import FRED_FEATURE_NAMES, fred_available
from equity_scout.ml.meta_model import MetaConfig, run_meta_model

MODELS = ("elastic_net", "random_forest", "catboost")
LOOKBACK_MONTHS = (6, 9, 12)
HORIZON_DAYS = (10, 21, 42)
BARRIERS = (0.03, 0.05, 0.08)
FEATURE_INCLUDE_PROB = 0.6
MIN_BETS = 20  # too few OOS bets → Sharpe is noise; skip


def _feature_pool() -> tuple[str, ...]:
    """The features the search may draw from. FRED macro features join only when a local snapshot
    exists, so the loop never samples a feature whose data it can't load."""
    return FEATURE_NAMES + (FRED_FEATURE_NAMES if fred_available() else ())


def sample_config(trial_index: int) -> MetaConfig:
    """Deterministic random draw keyed by the trial index."""
    rng = random.Random(trial_index)
    pool = _feature_pool()
    features = tuple(f for f in pool if rng.random() < FEATURE_INCLUDE_PROB)
    if len(features) < 2:  # always keep at least two dimensions
        features = tuple(rng.sample(list(pool), 2))
    return MetaConfig(
        features=features,
        model=rng.choice(MODELS),
        primary_lookback_months=rng.choice(LOOKBACK_MONTHS),
        horizon_days=rng.choice(HORIZON_DAYS),
        barrier=rng.choice(BARRIERS),
    )


@dataclass(frozen=True)
class EvalResult:
    config: MetaConfig
    trained: bool
    n_bets: int
    oos_hit_rate: float
    # compact stats so the ledger can recompute DSR as trials accumulate:
    sharpe_periodic: float
    n_obs: int
    skew: float
    kurtosis: float
    # display metrics (out-of-sample, after costs):
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    feature_importance: dict[str, float] = field(default_factory=dict)


def evaluate_config(panel: PricePanel, config: MetaConfig, *, costs_bps: float = 10.0) -> EvalResult:
    result = run_meta_model(panel, config, costs_bps=costs_bps)
    if not result.trained or result.n_bets < MIN_BETS:
        return EvalResult(config, False, result.n_bets, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    active = result.exposure[result.exposure > 0]
    start = active.index[0] if not active.empty else result.equity.index[0]
    equity = result.equity.loc[start:]
    equity = equity / equity.iloc[0]
    returns = daily_returns(equity)
    metrics = compute_metrics(equity)
    return EvalResult(
        config=config,
        trained=True,
        n_bets=result.n_bets,
        oos_hit_rate=result.oos_hit_rate,
        sharpe_periodic=periodic_sharpe(returns),
        n_obs=len(returns),
        skew=float(returns.skew()),
        kurtosis=float(returns.kurt()) + 3.0,  # raw kurtosis
        cagr=metrics.cagr,
        sharpe=metrics.sharpe,
        sortino=metrics.sortino,
        max_drawdown=metrics.max_drawdown,
        feature_importance=result.feature_importance,
    )
