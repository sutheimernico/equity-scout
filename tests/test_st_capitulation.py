"""Capitulation lane: entry rule, stop under the panic low, and the fast path pinned to the
definition that is already on screen."""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.st_capitulation import (
    capitulation_mask,
    decide,
    event_study,
)
from equity_scout.volume_signals import BASELINE_DAYS, read_volume


def _frame(closes: list[float], volumes: list[float]) -> tuple[pd.Series, pd.Series]:
    index = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.Series(closes, index=index), pd.Series(volumes, index=index, dtype=float)


def _panic_series() -> tuple[pd.Series, pd.Series]:
    closes = [100.0] * BASELINE_DAYS + [95.0]  # −5 % on the last day
    volumes = [1_000.0] * BASELINE_DAYS + [5_000.0]  # 5x the median
    return _frame(closes, volumes)


def test_buys_on_a_high_volume_decline() -> None:
    closes, volumes = _panic_series()
    action = decide("X", closes, volumes, entry_price=None, panic_low=None, days_held=0)
    assert action is not None and action.kind == "buy"
    assert "Kapitulation" in action.reason


def test_a_volume_spike_without_a_decline_is_not_capitulation() -> None:
    closes = [100.0] * BASELINE_DAYS + [104.0]  # up, not down
    volumes = [1_000.0] * BASELINE_DAYS + [5_000.0]
    c, v = _frame(closes, volumes)
    assert decide("X", c, v, entry_price=None, panic_low=None, days_held=0) is None


def test_a_decline_on_normal_volume_is_not_capitulation() -> None:
    closes = [100.0] * BASELINE_DAYS + [95.0]
    volumes = [1_000.0] * (BASELINE_DAYS + 1)
    c, v = _frame(closes, volumes)
    assert decide("X", c, v, entry_price=None, panic_low=None, days_held=0) is None


def test_stop_sits_below_the_panic_low_not_at_it() -> None:
    closes, volumes = _panic_series()
    # Panic low 95: the stop triggers below 95 * 0.98 = 93.1, not at 95 itself.
    at_low = decide("X", closes, volumes, entry_price=95.0, panic_low=95.0, days_held=1)
    assert at_low is None
    closes.iloc[-1] = 92.0
    below = decide("X", closes, volumes, entry_price=95.0, panic_low=95.0, days_held=1)
    assert below is not None and "Panik-Tief" in below.reason


def test_holding_period_closes_a_position_that_never_stopped_out() -> None:
    closes, volumes = _panic_series()
    action = decide("X", closes, volumes, entry_price=95.0, panic_low=90.0, days_held=20)
    assert action is not None and "Haltefrist" in action.reason


def test_event_study_matches_read_volume_day_for_day() -> None:
    """The fast path must agree with the definition the cockpit already shows.

    Two definitions of "capitulation" in one codebase drift apart silently, and the one in the
    trading rule is the one nobody looks at.
    """
    rng = np.random.default_rng(5)
    n = 200
    closes = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.02, n)),
                       index=pd.bdate_range("2024-01-01", periods=n))
    volumes = pd.Series(rng.lognormal(10, 0.8, n), index=closes.index)
    fast = capitulation_mask(closes, volumes)
    for i in range(BASELINE_DAYS + 1, n):
        slow = read_volume(
            "X", list(closes.iloc[: i + 1]), list(volumes.iloc[: i + 1])
        ).is_capitulation
        assert bool(fast.iloc[i]) == slow, f"Abweichung an Position {i}"


def test_event_study_reports_nothing_when_the_history_is_too_short() -> None:
    c, v = _frame([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert event_study(c, v)["n_events"] == 0
