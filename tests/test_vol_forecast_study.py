"""The volatility-forecast study's own machinery, on synthetic series (no snapshots, no network).

The study's conclusion drives a change to a LIVE risk layer, so the two things it measures must be
pinned separately: rank quality answers "does it flag the right days", calibration answers "is the
number in the right units". Conflating them is the trap the study exists to avoid — raw VIX ranks
best and would still throttle 36% too hard every day.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from equity_scout.behaviour_study import TRADING_DAYS_PER_YEAR, forward_volatility

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_vol_forecast_study import HORIZON, score, trailing_vol  # noqa: E402


def _regime_series(n: int = 3000, seed: int = 7) -> pd.Series:
    """A price series whose volatility switches between two regimes in long blocks, so a forward
    window is genuinely predictable from a contemporaneous level — the property the study looks
    for. Long blocks matter: with 20-day forwards, a regime shorter than that is unmeasurable.
    """
    rng = np.random.default_rng(seed)
    vols = np.where((np.arange(n) // 250) % 2 == 0, 0.005, 0.02)
    rets = rng.normal(0.0, vols)
    idx = pd.bdate_range("2007-01-03", periods=n)
    return pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx)


def test_trailing_vol_matches_the_protection_definition():
    """`trailing_vol` must be what VolTarget computes, or the study compares against a straw man."""
    closes = _regime_series(400)
    got = trailing_vol(closes, 20).dropna()
    rets = closes.pct_change()
    expected = rets.rolling(20).std(ddof=1).dropna() * math.sqrt(TRADING_DAYS_PER_YEAR)
    assert np.allclose(got.to_numpy(), expected.to_numpy())


def test_a_predictive_estimator_scores_a_positive_rank_correlation():
    closes = _regime_series()
    target = forward_volatility(closes, HORIZON)
    result = score(trailing_vol(closes), target)
    assert result["n"] >= 12
    assert result["rho"] is not None and result["rho"] > 0.3


def test_calibration_catches_an_estimator_that_is_scaled_wrong():
    """The point of measuring units separately: a 1.5x-inflated estimator keeps its perfect
    ranking and would still make VolTarget throttle half again too hard."""
    closes = _regime_series()
    target = forward_volatility(closes, HORIZON)
    honest = trailing_vol(closes)
    inflated = honest * 1.5
    assert score(inflated, target)["rho"] == score(honest, target)["rho"]
    assert score(inflated, target)["calibration"] > 1.4
    assert 0.8 < score(honest, target)["calibration"] < 1.25


def test_noise_shows_no_forecast_skill():
    """Guard against the study reporting skill where none exists."""
    closes = _regime_series()
    target = forward_volatility(closes, HORIZON)
    rng = np.random.default_rng(11)
    noise = pd.Series(rng.normal(size=len(closes)), index=closes.index)
    rho = score(noise, target)["rho"]
    assert rho is not None and abs(rho) < 0.25


def test_the_window_split_actually_restricts_the_sample():
    closes = _regime_series()
    target = forward_volatility(closes, HORIZON)
    trail = trailing_vol(closes)
    full = score(trail, target)["n"]
    first = score(trail, target, until="2013-01-01")["n"]
    second = score(trail, target, since="2013-01-01")["n"]
    assert first > 0 and second > 0
    assert first + second <= full + 1  # one boundary window may be dropped by either side


def test_too_few_independent_windows_reports_none_instead_of_a_number():
    """A short series must yield "not measurable", never a lucky correlation — the same honesty
    rule the behaviour study follows."""
    closes = _regime_series(120)
    target = forward_volatility(closes, HORIZON)
    result = score(trailing_vol(closes), target)
    assert result["rho"] is None
