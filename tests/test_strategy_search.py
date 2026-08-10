"""v14 strategy-parameter search: finite deterministic space, faithful factory,
offline backtest evaluation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.market import PricePanel
from equity_scout.ml.strategy_search import (
    STRATEGY_SPACE,
    StrategyConfig,
    all_configs,
    build_strategy,
    evaluate_strategy_config,
)
from equity_scout.strategies.dual_momentum import DualMomentumStrategy
from equity_scout.strategies.sector_rotation import SectorRotationStrategy
from equity_scout.strategies.sixty_forty import SixtyFortyStrategy
from equity_scout.strategies.vol_target import VolatilityTargetStrategy


def test_space_is_finite_with_unique_keys():
    configs = all_configs()
    expected = (
        4 * 4 + 4 + 3 + 4 * 4 + 4      # vol_target + gem + daa + sector_rotation + 60/40
        + 3 * 3                        # low_vol: top_n x vol_window            (v16)
        + 3 * 3 * 2                    # cross_momentum: top_n x lookback x skip (v16)
        + 3 * 3                        # mean_reversion: top_n x window          (v16)
        + 3                            # risk_parity: max_weight                 (v16)
    )
    assert len(configs) == expected == 82
    assert len({c.key() for c in configs}) == expected


def test_space_order_is_deterministic():
    assert all_configs() == all_configs()


def test_every_strategy_in_the_space_has_a_builder():
    for config in all_configs():
        assert build_strategy(config) is not None


def test_build_strategy_sets_exactly_the_sampled_params():
    vt = build_strategy(StrategyConfig("vol_target", (("target_vol", 0.15), ("vol_window_days", 21))))
    assert isinstance(vt, VolatilityTargetStrategy)
    assert vt.target_vol == 0.15 and vt.vol_window_days == 21
    assert vt.leverage_cap == 1.0  # untouched knobs stay at production defaults

    gem = build_strategy(StrategyConfig("gem", (("lookback_months", 6),)))
    assert isinstance(gem, DualMomentumStrategy)
    assert gem.lookback_months == 6 and gem.safe == "IEF"

    sr = build_strategy(StrategyConfig("sector_rotation", (("lookback_months", (12,)), ("top_n", 5))))
    assert isinstance(sr, SectorRotationStrategy)
    assert sr.top_n == 5 and sr.lookback_months == (12,)

    sf = build_strategy(StrategyConfig("sixty_forty", (("stock_weight", 0.7),)))
    assert isinstance(sf, SixtyFortyStrategy)
    assert sf.stock_weight == 0.7 and sf.name == "70/30"


def test_config_key_is_order_independent():
    a = StrategyConfig("vol_target", (("target_vol", 0.1), ("vol_window_days", 42)))
    b = StrategyConfig("vol_target", tuple(sorted((("vol_window_days", 42), ("target_vol", 0.1)))))
    assert a.key() == b.key()


def _panel(days: int = 300) -> PricePanel:
    idx = pd.bdate_range("2024-01-01", periods=days)
    rng = np.random.default_rng(7)
    spy = 100.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.01, days))
    ief = 100.0 * np.cumprod(1.0 + rng.normal(0.0001, 0.003, days))
    return PricePanel(pd.DataFrame({"SPY": spy, "IEF": ief}, index=idx))


def test_evaluate_runs_an_after_cost_backtest_offline():
    result = evaluate_strategy_config(
        _panel(), StrategyConfig("sixty_forty", (("stock_weight", 0.6),))
    )
    assert result.n_obs == 299
    assert result.annual_turnover >= 0.0
    assert -1.0 <= result.max_drawdown <= 0.0
    assert result.kurtosis > 0.0  # raw kurtosis (+3), never the excess form
    assert result.config.strategy == "sixty_forty"


def test_evaluate_vol_target_uses_the_sampled_window():
    short = evaluate_strategy_config(
        _panel(), StrategyConfig("vol_target", (("target_vol", 0.08), ("vol_window_days", 21)))
    )
    long = evaluate_strategy_config(
        _panel(), StrategyConfig("vol_target", (("target_vol", 0.15), ("vol_window_days", 126)))
    )
    # different knobs must produce different equity paths on the same panel
    assert short.sharpe_periodic != long.sharpe_periodic


def test_space_never_contains_leverage():
    for config in all_configs():
        params = config.params_dict()
        assert "leverage_cap" not in params
        assert STRATEGY_SPACE[config.strategy].keys() == params.keys()
