import math

import pytest

from equity_scout.entry import atr, compute_entry_plan, fib_levels, recent_swing_low, sma


def test_sma_uses_last_window():
    # last 3 of [1,2,3,4,5,6] -> mean(4,5,6) = 5.0
    assert sma([1, 2, 3, 4, 5, 6], window=3) == 5.0


def test_sma_falls_back_to_all_when_short():
    # fewer points than window -> mean of all
    assert sma([10, 20], window=200) == 15.0


def test_sma_empty_is_none():
    assert sma([], window=3) is None


def test_fib_levels_from_high_low():
    # range 100..200; retracement from the high: high - range*ratio
    levels = fib_levels(high=200.0, low=100.0)
    assert levels["0.382"] == 200.0 - 100.0 * 0.382
    assert levels["0.5"] == 150.0
    assert math.isclose(levels["0.618"], 200.0 - 100.0 * 0.618)


def test_recent_swing_low_finds_latest_local_min():
    # local minima at index 2 (value 1) and index 8 (value 2); latest is value 2
    closes = [9, 5, 1, 5, 9, 8, 6, 4, 2, 4, 7]
    assert recent_swing_low(closes, k=2) == 2.0


def test_recent_swing_low_none_when_monotone():
    assert recent_swing_low([1, 2, 3, 4, 5], k=2) is None


def test_atr_is_mean_true_range():
    # constant daily range of 2 (high-low), no gaps -> ATR = 2.0
    highs = [12, 12, 12, 12, 12]
    lows = [10, 10, 10, 10, 10]
    closes = [11, 11, 11, 11, 11]
    assert atr(highs, lows, closes, window=4) == 2.0


def test_atr_drops_nan_rows():
    # one NaN row in the middle is dropped; the rest still yield a clean ATR of 2.0
    highs = [12, 12, float("nan"), 12, 12]
    lows = [10, 10, float("nan"), 10, 10]
    closes = [11, 11, float("nan"), 11, 11]
    assert atr(highs, lows, closes, window=4) == 2.0


def test_atr_none_on_length_mismatch():
    assert atr([12, 12], [10], [11, 11]) is None


def _ramp_then_dip() -> tuple[list[float], list[float], list[float]]:
    # 260 trading days: rise 100->200 then pull back to 160. Highs/Lows bracket closes by ±1.
    rising = [100 + i * (100 / 199) for i in range(200)]   # 100 .. 200
    falling = [200 - i * (40 / 59) for i in range(1, 61)]  # ~199.3 .. 160
    closes = rising + falling
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return closes, highs, lows


def test_compute_entry_plan_core_levels():
    closes, highs, lows = _ramp_then_dip()
    plan = compute_entry_plan("TEST", closes, highs, lows)

    assert plan.ticker == "TEST"
    assert plan.price == round(closes[-1], 2)       # last close ~160
    assert plan.high_52w == round(max(highs), 2)    # ~201
    assert plan.low_52w == round(min(lows), 2)      # ~99
    assert plan.sma200 is not None
    # current price (~160) is below the 200-day SMA of a long uptrend -> below "fair value"
    assert plan.price < plan.sma200
    # drawdown from the high is negative
    assert plan.drawdown_from_high < 0


def test_compute_entry_plan_tranches_sum_to_one():
    closes, highs, lows = _ramp_then_dip()
    plan = compute_entry_plan("TEST", closes, highs, lows)

    assert len(plan.dca_tranches) == 4
    assert math.isclose(sum(t.fraction for t in plan.dca_tranches), 1.0)
    assert math.isclose(sum(t.fraction for t in plan.dip_tranches), 1.0)
    # DCA tranches are time-based (no trigger price); dip tranches have descending triggers
    assert all(t.trigger_price is None for t in plan.dca_tranches)
    triggers = [t.trigger_price for t in plan.dip_tranches]
    assert triggers == sorted(triggers, reverse=True)


def test_compute_entry_plan_levels_present():
    closes, highs, lows = _ramp_then_dip()
    plan = compute_entry_plan("TEST", closes, highs, lows)
    labels = {lvl.label for lvl in plan.levels}
    assert "200-Tage-Schnitt" in labels
    assert "Fibonacci 61.8 %" in labels


def test_compute_entry_plan_handles_short_history():
    # Two points only — must not crash, sma falls back, atr is None.
    plan = compute_entry_plan("X", [100.0, 110.0], [101.0, 111.0], [99.0, 109.0])
    assert plan.price == 110.0
    assert plan.atr is None


def test_compute_entry_plan_raises_on_no_valid_closes():
    with pytest.raises(ValueError):
        compute_entry_plan("BAD", [], [], [])


def test_flat_price_yields_no_atr_and_consistent_state():
    # Perfectly flat price -> ATR 0.0. The atr field and the ATR levels must agree: both absent.
    closes = [100.0] * 20
    plan = compute_entry_plan("FLAT", closes, list(closes), list(closes))
    assert plan.atr is None
    assert not any("ATR" in lvl.label for lvl in plan.levels)


def test_near_reference_true_when_below_anchor_and_near_support():
    # V-shape: long decline 200->~100 then a small bounce to ~104. Price sits below the 200d
    # SMA and inside the fib-61.8 zone, so near_reference must be True.
    decline = [200 - i * (100 / 209) for i in range(210)]
    bounce = [100 + i * (4 / 49) for i in range(1, 51)]
    closes = decline + bounce
    plan = compute_entry_plan("V", closes, [c + 1 for c in closes], [c - 1 for c in closes])
    assert plan.sma200 is not None and plan.price < plan.sma200
    assert plan.near_reference is True


def test_near_reference_false_when_above_anchor():
    # Monotonic rise 100->200: price ends at the high, well above the SMA -> not in a zone.
    closes = [100 + i * (100 / 259) for i in range(260)]
    plan = compute_entry_plan("UP", closes, [c + 1 for c in closes], [c - 1 for c in closes])
    assert plan.sma200 is not None and plan.price > plan.sma200
    assert plan.near_reference is False
