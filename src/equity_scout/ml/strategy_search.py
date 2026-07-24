"""Search space + evaluation for the strategy-parameter research loop (v14, P7/v5-P4).

Second search dimension next to the ML meta-model search (`ml/search.py`): the tunable
knobs of the RULE strategies. The space is a small, finite, deterministically enumerated
grid — honesty over breadth: every additional trial raises the DSR hurdle in the strategy
ledger, so the grid holds only parameters with an economic story (no leverage > 1: the
backtest has no borrow model; no Permanent-Portfolio grid: the fixed 4x25% IS the
strategy; no DCA grid: tranches only matter in the ramp-up, meaningless whole-history).

A trial is a whole-history after-cost backtest (`engine.run_backtest`) — IN-SAMPLE by
construction, deflated by the strategy pool's own expected-max-Sharpe. Champions are
evidence for Nico, never auto-promoted: changed parameters are a NEW strategy identity
and would rewrite the sleeves' forward track records (same argument as the ensemble
composition note in `strategies/registry.py`).

Grid growth note: `all_configs()` order is itertools.product over the literal space —
extending a grid shifts cursor positions. That is harmless (the ledger upserts per
config_key and the cursor wraps modulo the space size), so the order carries no contract
beyond "stable for a given space".
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import product

from equity_scout.engine import run_backtest
from equity_scout.market import PricePanel
from equity_scout.metrics import compute_metrics, daily_returns, periodic_sharpe
from equity_scout.strategies.daa import DefensiveAssetAllocationStrategy
from equity_scout.strategies.dual_momentum import DualMomentumStrategy
from equity_scout.strategies.sector_rotation import SectorRotationStrategy
from equity_scout.strategies.sixty_forty import SixtyFortyStrategy
from equity_scout.strategies.vol_target import VolatilityTargetStrategy

# Strategy key -> parameter name -> candidate values. Tuples of tuples stay tuples all
# the way into the constructors (sector rotation's lookback blend).
STRATEGY_SPACE: dict[str, dict[str, tuple]] = {
    "vol_target": {
        "target_vol": (0.08, 0.10, 0.12, 0.15),
        "vol_window_days": (21, 42, 63, 126),
    },
    "gem": {"lookback_months": (3, 6, 9, 12)},
    "daa": {"top_n": (2, 3, 4)},
    "sector_rotation": {
        "top_n": (2, 3, 4, 5),
        "lookback_months": ((12, 6), (6, 3), (12,), (9, 3)),
    },
    "sixty_forty": {"stock_weight": (0.5, 0.6, 0.7, 0.8)},
}

_BUILDERS = {
    "vol_target": VolatilityTargetStrategy,
    "gem": DualMomentumStrategy,
    "daa": DefensiveAssetAllocationStrategy,
    "sector_rotation": SectorRotationStrategy,
    "sixty_forty": SixtyFortyStrategy,
}


@dataclass(frozen=True)
class StrategyConfig:
    """One point in the strategy-parameter space. `params` is a sorted tuple of
    (name, value) pairs so the config is hashable and its key deterministic."""

    strategy: str
    params: tuple[tuple[str, object], ...]

    def params_dict(self) -> dict:
        return dict(self.params)

    def key(self) -> str:
        return json.dumps(
            {"strategy": self.strategy, "params": self.params_dict()}, sort_keys=True
        )


@dataclass(frozen=True)
class StrategyEvalResult:
    """One trial's outcome: the four PSR statistics (raw kurtosis, +3 like
    `probabilistic_sharpe_ratio`) plus the headline metrics the ledger displays."""

    config: StrategyConfig
    sharpe_periodic: float
    n_obs: int
    skew: float
    kurtosis: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    annual_turnover: float


def all_configs() -> list[StrategyConfig]:
    """The full space in a stable order (see module docstring on grid growth)."""
    configs: list[StrategyConfig] = []
    for strategy, grid in STRATEGY_SPACE.items():
        names = list(grid)
        for values in product(*(grid[n] for n in names)):
            params = tuple(sorted(zip(names, values)))
            configs.append(StrategyConfig(strategy=strategy, params=params))
    return configs


def build_strategy(config: StrategyConfig):
    """Instantiate the rule strategy this config describes; all other knobs stay at the
    production defaults, so a trial differs from the live sleeve in exactly the sampled
    parameters."""
    return _BUILDERS[config.strategy](**config.params_dict())


def evaluate_strategy_config(
    panel: PricePanel,
    config: StrategyConfig,
    *,
    rebalance: str = "ME",
    costs_bps: float = 10.0,
) -> StrategyEvalResult:
    """One whole-history after-cost backtest -> compact stats for the strategy ledger.
    Same conventions as scripts/run_backtest.py (ME rebalance, 10 bps round-trip)."""
    result = run_backtest(build_strategy(config), panel, rebalance=rebalance, costs_bps=costs_bps)
    rets = daily_returns(result.equity)
    m = compute_metrics(result.equity)
    return StrategyEvalResult(
        config=config,
        sharpe_periodic=periodic_sharpe(rets),
        n_obs=len(rets),
        skew=float(rets.skew()),
        kurtosis=float(rets.kurt()) + 3.0,  # pandas is excess; PSR wants raw
        cagr=m.cagr,
        sharpe=m.sharpe,
        sortino=m.sortino,
        max_drawdown=m.max_drawdown,
        annual_turnover=result.annual_turnover,
    )
