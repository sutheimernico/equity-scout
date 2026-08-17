"""Resampling 1-minute bars onto the slice axis without welding sessions together."""
import pandas as pd
import pytest

from equity_scout.matrix.timeframes import (
    INTRADAY_SLICES,
    TIME_SLICES,
    resample_bars,
    slice_minutes,
)


def _minutes(day: str, count: int, start_utc: str = "14:30") -> pd.DataFrame:
    index = pd.date_range(f"{day}T{start_utc}:00Z", periods=count, freq="1min")
    return pd.DataFrame(
        {"open": range(1, count + 1), "high": range(2, count + 2),
         "low": range(0, count), "close": range(1, count + 1),
         "volume": [100] * count},
        index=index, dtype=float,
    )


def test_five_minute_bars_aggregate_ohlcv_correctly():
    out = resample_bars(_minutes("2024-01-02", 10), "5min")
    assert len(out) == 2
    first = out.iloc[0]
    assert first["open"] == 1.0 and first["close"] == 5.0
    assert first["high"] == 6.0 and first["low"] == 0.0
    assert first["volume"] == 500.0


def test_an_intraday_bar_never_spans_two_trading_days():
    frame = pd.concat([_minutes("2024-01-02", 3), _minutes("2024-01-03", 3)])
    out = resample_bars(frame, "5min")
    # 3 minutes per day: each day yields its own partial bar, never one merged bar
    assert len(out) == 2
    assert [str(ts.date()) for ts in out.index] == ["2024-01-02", "2024-01-03"]


def test_partial_trailing_bar_is_dropped_when_incomplete_is_false():
    out = resample_bars(_minutes("2024-01-02", 7), "5min", keep_incomplete=False)
    assert len(out) == 1  # the 2-minute remainder is not a 5-minute bar


def test_one_minute_passthrough_is_identity():
    frame = _minutes("2024-01-02", 4)
    assert resample_bars(frame, "1min").equals(frame)


def test_daily_slice_spans_sessions_on_purpose():
    frame = pd.concat([_minutes("2024-01-02", 3), _minutes("2024-01-03", 3)])
    out = resample_bars(frame, "1D")
    assert len(out) == 2  # one bar per day, built across the whole session
    assert out["volume"].tolist() == [300.0, 300.0]


def test_weekly_and_monthly_slices_collapse_further():
    frame = pd.concat([
        _minutes("2024-01-02", 2), _minutes("2024-01-03", 2),  # same week
        _minutes("2024-02-05", 2),  # next month
    ])
    assert len(resample_bars(frame, "1W")) == 2
    assert len(resample_bars(frame, "1M")) == 2


def test_swing_slices_have_no_fixed_minute_count():
    assert slice_minutes("15min") == 15
    with pytest.raises(ValueError, match="keine Intraday-Scheibe"):
        slice_minutes("1D")


def test_the_axis_is_ordered_fine_to_coarse():
    assert TIME_SLICES == ("1min", "5min", "15min", "30min", "60min", "1D", "1W", "1M")
    assert INTRADAY_SLICES == TIME_SLICES[:5]
