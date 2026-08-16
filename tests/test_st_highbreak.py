"""52-week-high lane: breakout detection, trailing stop, and a leak-free event study."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.st_highbreak import (
    LOOKBACK_DAYS,
    decide,
    event_study,
    is_breakout,
)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)))


def test_breakout_needs_to_beat_every_close_in_the_window() -> None:
    rising = _series([100.0] * LOOKBACK_DAYS + [101.0])
    assert is_breakout(rising)
    flat = _series([100.0] * LOOKBACK_DAYS + [100.0])
    assert not is_breakout(flat)  # equal is not above


def test_the_signal_day_is_not_part_of_its_own_window() -> None:
    """Including the signal session makes every day its own maximum — the rule would fire
    constantly and the backtest would look excellent for a reason that is a bug."""
    values = [100.0] * (LOOKBACK_DAYS - 1) + [150.0, 120.0]
    assert not is_breakout(_series(values))  # 120 < the 150 that sits inside the window


def test_too_short_a_history_is_not_a_breakout() -> None:
    assert not is_breakout(_series([1.0, 2.0, 3.0]))


def test_trailing_stop_sells_after_the_peak_not_after_the_entry() -> None:
    closes = _series([100.0, 120.0, 107.0])
    action = decide("X", closes, entry_price=100.0, peak_since_entry=120.0, days_held=3)
    assert action is not None and action.kind == "sell"
    # Still above the stop measured from the peak (120 * 0.9 = 108) -> hold.
    held = decide("X", _series([100.0, 120.0, 109.0]), entry_price=100.0,
                  peak_since_entry=120.0, days_held=3)
    assert held is None


def test_max_holding_closes_a_position_that_never_stopped_out() -> None:
    closes = _series([100.0, 101.0])
    action = decide("X", closes, entry_price=100.0, peak_since_entry=101.0, days_held=60)
    assert action is not None and "Haltefrist" in action.reason


def test_event_study_uses_only_past_data_for_the_signal() -> None:
    """A rolling max that includes today leaks the answer into the signal."""
    rng = np.random.default_rng(3)
    closes = _series(list(100 * np.cumprod(1 + rng.normal(0, 0.01, LOOKBACK_DAYS + 200))))
    result = event_study(closes, horizon=20)
    assert result["n_events"] > 0
    assert result["n_other"] > result["n_events"]
    # Forward windows that run past the end of the series must not be counted as zero.
    assert result["n_events"] + result["n_other"] <= len(closes) - 20


def test_event_study_reports_nothing_when_the_history_is_too_short() -> None:
    assert event_study(_series([1.0, 2.0, 3.0]))["n_events"] == 0
