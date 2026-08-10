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
from equity_scout.strategies.cross_momentum import CrossSectionalMomentumStrategy
from equity_scout.strategies.daa import DefensiveAssetAllocationStrategy
from equity_scout.strategies.dual_momentum import DualMomentumStrategy
from equity_scout.strategies.low_vol import LowVolatilityStrategy
from equity_scout.strategies.mean_reversion import MeanReversionStrategy
from equity_scout.strategies.risk_parity import RiskParityStrategy
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
    # v16 families. Kept deliberately narrow — the module's own rule is that every extra
    # trial raises the DSR hurdle, so only knobs with an economic story get a grid. The
    # first-pass defaults came from the literature, not from fitting this panel; the grid
    # exists so the nightly loop can test whether they hold HERE, on real data, instead of
    # leaving my starting values unchallenged forever.
    "low_vol": {
        # How wide the calm basket is, and over what horizon "calm" is measured. Both change
        # the strategy's character; the safe/hurdle tickers do not and stay fixed.
        "top_n": (3, 5, 7),
        "vol_window_days": (21, 63, 126),
    },
    "cross_momentum": {
        "top_n": (2, 3, 4),
        "lookback_months": (6, 9, 12),
        # 0 vs 1 is the skip-month question itself. Jegadeesh/Titman answered it for US
        # single stocks in 1993; whether it holds for THIS 21-ETF universe is an empirical
        # question worth one dimension of the grid rather than an assumption.
        "skip_months": (0, 1),
    },
    "mean_reversion": {
        # The reversion horizon is the whole thesis (and drives the turnover that ate the
        # first backtest: 16x/year at 2.7% CAGR). 5/10/21 days spans "bounce" to "monthly".
        "top_n": (2, 3, 5),
        "reversion_window_days": (5, 10, 21),
    },
    # Only the cap: the sleeve composition is the strategy (same argument as the
    # Permanent-Portfolio exclusion above), and the vol window barely moves an
    # inverse-vol book.
    "risk_parity": {"max_weight": (0.25, 0.40, 0.60)},
}

_BUILDERS = {
    "vol_target": VolatilityTargetStrategy,
    "gem": DualMomentumStrategy,
    "daa": DefensiveAssetAllocationStrategy,
    "sector_rotation": SectorRotationStrategy,
    "sixty_forty": SixtyFortyStrategy,
    "low_vol": LowVolatilityStrategy,
    "cross_momentum": CrossSectionalMomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "risk_parity": RiskParityStrategy,
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
