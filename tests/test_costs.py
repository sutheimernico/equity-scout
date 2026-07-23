"""Corwin-Schultz cost floor (v13 O3): closed-form check, clipping, honest fallback."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.costs import FLAT_FLOOR_BPS, cs_spread, fill_cost_rate_bps


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range("2026-06-01", periods=len(values)))


def test_cs_spread_matches_the_closed_form_for_constant_ranges():
    """With identical days (H=102, L=100, no overnight move) the CS algebra collapses to
    alpha = ln(H/L)/... -> exactly S = 2*(H/L - 1)/(1 + H/L): here 0.04/2.02."""
    days = 10
    spread = cs_spread(_series([102.0] * days), _series([100.0] * days))
    assert spread == pytest.approx(2.0 * 0.02 / 2.02, rel=1e-9)


def test_cs_spread_clips_negative_days_to_zero():
    # tiny daily ranges but a huge overnight gap: gamma >> beta -> raw estimate < 0
    high = _series([100.5, 140.5])
    low = _series([100.0, 140.0])
    assert cs_spread(high, low) == 0.0


def test_cs_spread_needs_two_clean_days():
    assert cs_spread(_series([102.0]), _series([100.0])) == 0.0
    nan = float("nan")
    assert cs_spread(_series([102.0, nan]), _series([100.0, nan])) == 0.0
    assert cs_spread(_series([102.0, -1.0]), _series([100.0, -2.0])) == 0.0


def test_fill_cost_rate_floor_and_liquidity_surcharge(caplog):
    # liquid name: ~2 bps estimated spread -> the flat floor wins
    tight = pd.DataFrame({
        "high": np.full(22, 100.02), "low": np.full(22, 100.0),
        "open": np.full(22, 100.0), "close": np.full(22, 100.01),
    }, index=pd.bdate_range("2026-06-01", periods=22))
    assert fill_cost_rate_bps(tight) == FLAT_FLOOR_BPS

    # thin name: ~198 bps spread -> half of it beats the floor
    wide = pd.DataFrame({
        "high": np.full(22, 102.0), "low": np.full(22, 100.0),
    }, index=pd.bdate_range("2026-06-01", periods=22))
    expected_half_spread = 2.0 * 0.02 / 2.02 / 2.0 * 10_000.0
    assert fill_cost_rate_bps(wide) == pytest.approx(expected_half_spread)

    # no OHLC at all (lane fund shares, feed gap): flat floor, logged
    import logging

    with caplog.at_level(logging.INFO, logger="equity_scout.costs"):
        assert fill_cost_rate_bps(None) == FLAT_FLOOR_BPS
    assert "flat" in caplog.text
