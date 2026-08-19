"""Signal detectors: each fires on its constructed case, stays silent otherwise, no look-ahead."""
import pandas as pd

from equity_scout.matrix.signals import (
    SIGNALS,
    breakout_high,
    bullish_engulfing,
    hammer,
    momentum_up,
    reversal_down,
    volume_spike,
)


def _bars(rows: list[dict]) -> pd.DataFrame:
    index = pd.date_range("2024-01-02T14:30:00Z", periods=len(rows), freq="5min")
    return pd.DataFrame(rows, index=index, dtype=float)


def test_registry_exposes_every_detector_with_a_plateau_capable_axis():
    assert set(SIGNALS) == {
        "momentum_up", "reversal_down", "volume_spike", "breakout_high",
        "hammer", "bullish_engulfing", "gap_up", "gap_down", "spike_pullback",
        "spike_fade", "consecutive_down", "range_contraction", "new_low_20",
        "catalyst_age", "catalyst_volume_spike",
    }
    for name, spec in SIGNALS.items():
        assert callable(spec.detect), name
        assert len(spec.thresholds) >= 4, name  # a short axis cannot form a plateau


def test_momentum_up_fires_only_above_the_threshold():
    bars = _bars([
        {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 10},
        {"open": 100, "high": 103, "low": 100, "close": 103, "volume": 10},  # +3 %
        {"open": 103, "high": 103.1, "low": 103, "close": 103.1, "volume": 10},  # +0.1 %
    ])
    assert momentum_up(bars, threshold=0.02).tolist() == [False, True, False]


def test_reversal_down_fires_after_a_drop():
    bars = _bars([
        {"open": 100, "high": 100, "low": 100, "close": 100, "volume": 10},
        {"open": 100, "high": 100, "low": 96, "close": 97, "volume": 10},  # -3 %
    ])
    assert reversal_down(bars, threshold=0.02).tolist() == [False, True]


def test_volume_spike_needs_a_multiple_of_the_trailing_median():
    rows = [{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 100} for _ in range(25)]
    rows[-1]["volume"] = 400  # 4x the median
    fired = volume_spike(_bars(rows), threshold=3.0)
    assert fired.iloc[-1] and not fired.iloc[-2]


def test_breakout_high_needs_a_new_high_over_the_lookback():
    rows = [{"open": 100, "high": 100, "low": 100, "close": 100, "volume": 10} for _ in range(21)]
    rows[-1] = {"open": 100, "high": 105, "low": 100, "close": 105, "volume": 10}
    fired = breakout_high(_bars(rows), threshold=0.0)
    assert fired.iloc[-1] and not fired.iloc[-2]


def test_hammer_needs_a_long_lower_wick_and_a_small_body():
    bars = _bars([
        # body 100->100.2 (0.2), lower wick 100->97 (3.0): wick >> body, close near the high
        {"open": 100, "high": 100.3, "low": 97.0, "close": 100.2, "volume": 10},
        # a plain up-bar is not a hammer
        {"open": 100, "high": 103, "low": 99.9, "close": 102.9, "volume": 10},
    ])
    assert hammer(bars, threshold=2.0).tolist() == [True, False]


def test_a_zero_body_bar_is_not_a_hammer():
    bars = _bars([{"open": 100, "high": 100, "low": 97, "close": 100, "volume": 10}])
    assert hammer(bars, threshold=2.0).tolist() == [False]


def test_bullish_engulfing_needs_the_previous_body_covered():
    bars = _bars([
        {"open": 101, "high": 101, "low": 99, "close": 99, "volume": 10},   # down bar 101->99
        {"open": 98.5, "high": 102, "low": 98.4, "close": 101.5, "volume": 10},  # engulfs it
        {"open": 101.5, "high": 102, "low": 101, "close": 101.6, "volume": 10},  # tiny up bar
    ])
    assert bullish_engulfing(bars, threshold=1.0).tolist() == [False, True, False]


def test_no_detector_looks_into_the_future():
    # Truncating the frame must not change earlier flags. A detector that peeked would differ.
    rows = [
        {"open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i, "volume": 10 + i}
        for i in range(30)
    ]
    full_frame, head_frame = _bars(rows), _bars(rows[:8])
    for name, spec in SIGNALS.items():
        full = spec.detect(full_frame, threshold=spec.thresholds[0])
        head = spec.detect(head_frame, threshold=spec.thresholds[0])
        assert full.iloc[:8].tolist() == head.tolist(), name
