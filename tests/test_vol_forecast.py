"""vol_forecast: the VIX-calibrated multiplier for VolTarget (study 2026-08-12)."""
import math

import pandas as pd

from equity_scout.vol_forecast import (
    MULTIPLIER_CLAMP,
    TRAILING_WINDOW,
    VIX_DIVISOR,
    trailing_vol,
    vix_multiplier,
)


def _flat_closes(n: int = 40, daily_return: float = 0.01) -> pd.Series:
    # alternating +1%/-1% days -> stable, known trailing vol
    values, price = [], 100.0
    for i in range(n):
        price *= 1.0 + (daily_return if i % 2 == 0 else -daily_return)
        values.append(price)
    return pd.Series(values, index=pd.bdate_range("2026-01-01", periods=n))


def test_trailing_vol_needs_enough_history():
    assert trailing_vol(_flat_closes(n=TRAILING_WINDOW - 1)) is None


def test_trailing_vol_is_annualised_and_positive():
    vol = trailing_vol(_flat_closes())
    assert vol is not None and 0.1 < vol < 0.3  # ~1% daily -> ~16% annualised


def test_multiplier_is_forecast_over_trailing():
    closes = _flat_closes()
    spy_trailing = trailing_vol(closes)
    vix_level = 20.0
    expected = (vix_level / 100.0 / VIX_DIVISOR) / spy_trailing
    result = vix_multiplier(vix_level, closes)
    assert result is not None
    assert math.isclose(result, expected, rel_tol=1e-9)


def test_missing_inputs_yield_none():
    assert vix_multiplier(None, _flat_closes()) is None
    assert vix_multiplier(20.0, None) is None
    assert vix_multiplier(20.0, _flat_closes(n=5)) is None


def test_implausibly_low_ratio_is_distrusted_not_clipped():
    # a bad print (VIX 0.16 instead of 16) must NOT switch the protection off
    assert vix_multiplier(0.16, _flat_closes()) is None


def test_high_ratio_is_clipped_to_the_cap_not_distrusted():
    # a genuine spike must keep throttling (more throttle is the safe direction)
    result = vix_multiplier(500.0, _flat_closes())
    assert result == MULTIPLIER_CLAMP[1]
