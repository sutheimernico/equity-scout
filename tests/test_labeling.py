"""Triple-barrier labeling building blocks: on_timeout policies, trailing vol, BarrierConfig.

`triple_barrier_labels`'s default (`on_timeout="sign"`, the meta-model's original behaviour) is
already covered in test_ml.py — these tests focus on what `entry_tb` adds: the "zero" timeout
policy, vol-scaled barrier inputs, and the persisted barrier-config shape.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.ml.labeling import BarrierConfig, trailing_daily_vol, triple_barrier_labels


def _series(prices: list[float], start: str = "2020-01-01") -> pd.Series:
    return pd.Series(prices, index=pd.bdate_range(start, periods=len(prices)))


# --- on_timeout="zero" (entry_tb's policy) ---
def test_on_timeout_zero_labels_profit_hit_first_as_one():
    prices = _series([100.0 * 1.02**i for i in range(8)])  # +2%/day → +5% within a few days
    labels = triple_barrier_labels(
        prices, prices.index[:1], horizon_days=6, profit_take=0.05, stop_loss=0.05, on_timeout="zero"
    )
    assert labels.iloc[0] == 1


def test_on_timeout_zero_labels_stop_hit_first_as_zero():
    prices = _series([100.0 * 0.98**i for i in range(8)])  # -2%/day → -5% first
    labels = triple_barrier_labels(
        prices, prices.index[:1], horizon_days=6, profit_take=0.05, stop_loss=0.05, on_timeout="zero"
    )
    assert labels.iloc[0] == 0


def test_on_timeout_zero_labels_a_pure_timeout_as_zero_not_sign():
    # Drifts up slowly, never touches ±5% within the horizon. `on_timeout="sign"` (test_ml.py) calls
    # this 1 (ended higher); entry_tb's "zero" policy must call it 0 — reaching the target is what
    # matters, not merely ending up.
    prices = _series([100.0 + 0.1 * i for i in range(8)])
    labels = triple_barrier_labels(
        prices, prices.index[:1], horizon_days=6, profit_take=0.05, stop_loss=0.05, on_timeout="zero"
    )
    assert labels.iloc[0] == 0


def test_invalid_on_timeout_raises():
    prices = _series([100.0] * 8)
    with pytest.raises(ValueError):
        triple_barrier_labels(prices, prices.index[:1], on_timeout="bogus")


# --- trailing_daily_vol ---
def test_trailing_daily_vol_nan_before_window_is_full():
    prices = _series([100.0 + i for i in range(10)])
    vol = trailing_daily_vol(prices, window=5)
    assert vol.iloc[:5].isna().all()
    assert np.isfinite(vol.iloc[-1])


def test_trailing_daily_vol_matches_manual_rolling_std():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0, 0.01, size=100)
    prices = _series((100.0 * np.cumprod(1.0 + rets)).tolist())
    vol = trailing_daily_vol(prices, window=20)
    manual = prices.pct_change().iloc[-20:].std(ddof=1)
    assert vol.iloc[-1] == pytest.approx(manual)


def test_trailing_daily_vol_not_annualized():
    # A constant +1%/day return has zero variance (std=0), so the annualization factor cannot be
    # inferred from this alone — instead: assert the value is the raw daily std, not scaled by
    # sqrt(252), on a series with real dispersion.
    prices = _series([100.0 * (1.01 if i % 2 == 0 else 0.99) ** 1 for i in range(30)])
    vol = trailing_daily_vol(prices, window=10)
    manual = prices.pct_change().iloc[-10:].std(ddof=1)
    assert vol.iloc[-1] == pytest.approx(manual)
    assert vol.iloc[-1] != pytest.approx(manual * np.sqrt(252))  # would be the case if annualized


def test_vol_scaling_widens_the_barrier_for_a_more_volatile_ticker():
    """The whole point of scaling by sigma instead of a fixed fraction: a more volatile ticker's
    trailing sigma is larger, so k_pt * sigma is a wider barrier for it than for a calm ticker."""
    calm = _series([100.0 + 0.05 * ((-1) ** i) for i in range(70)])
    wild = _series([100.0 + 4.0 * ((-1) ** i) for i in range(70)])
    sigma_calm = trailing_daily_vol(calm, window=60).iloc[-1]
    sigma_wild = trailing_daily_vol(wild, window=60).iloc[-1]
    assert sigma_wild > sigma_calm > 0

    k_pt = 2.0
    assert k_pt * sigma_wild > k_pt * sigma_calm


# --- BarrierConfig ---
def test_barrier_config_defaults_match_the_task_preset():
    config = BarrierConfig()
    assert config.k_pt == 2.0
    assert config.k_sl == 1.0
    assert config.horizon_days == 40
    assert config.vol_window == 60


def test_barrier_config_as_dict_roundtrips_through_json():
    import json

    config = BarrierConfig(k_pt=1.5, k_sl=0.8, horizon_days=30, vol_window=45)
    restored = json.loads(json.dumps(config.as_dict()))
    assert restored == {"k_pt": 1.5, "k_sl": 0.8, "horizon_days": 30, "vol_window": 45}
    assert BarrierConfig(**restored) == config
