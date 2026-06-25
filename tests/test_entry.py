import math

from equity_scout.entry import atr, fib_levels, recent_swing_low, sma


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
