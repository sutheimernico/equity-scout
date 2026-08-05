"""Alpaca IEX bars must satisfy the exact contract intraday_bars.fetch_bars satisfies:
tz-aware America/New_York index, lowercase open/high/low/close columns. st_session.decide()
must not be able to tell the two feeds apart."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from equity_scout.alpaca_data import (
    RANGE_BAR_MINUTES,
    TRIGGER_BAR_MINUTES,
    AlpacaDataError,
    complete_bars,
    parse_bars,
)


def _payload() -> dict:
    return {
        "bars": {
            "AAPL": [
                {"t": "2026-08-04T13:30:00Z", "o": 300.0, "h": 302.0, "l": 299.5,
                 "c": 301.0, "v": 1000},
                {"t": "2026-08-04T13:45:00Z", "o": 301.0, "h": 303.0, "l": 300.5,
                 "c": 302.5, "v": 1200},
            ]
        }
    }


def test_parse_yields_new_york_index_and_lowercase_columns() -> None:
    frames = parse_bars(_payload())
    frame = frames["AAPL"]
    assert str(frame.index.tz) == "America/New_York"
    assert frame.index[0].hour == 9 and frame.index[0].minute == 30
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert frame["close"].iloc[-1] == 302.5


def test_empty_series_is_absent_not_zero() -> None:
    assert parse_bars({"bars": {"AAPL": []}}) == {}


def test_missing_bars_key_raises_loudly() -> None:
    with pytest.raises(AlpacaDataError, match="kein 'bars'"):
        parse_bars({"message": "forbidden"})


def test_complete_bars_drops_the_still_running_interval() -> None:
    frames = parse_bars(_payload())
    # 09:45 bar covers 09:45-10:00; at 09:52 it is not finished yet.
    now = datetime(2026, 8, 4, 9, 52, tzinfo=ZoneInfo("America/New_York"))
    kept = complete_bars(frames["AAPL"], now, bar_minutes=RANGE_BAR_MINUTES)
    assert len(kept) == 1
    assert kept.index[-1].minute == 30


def test_complete_bars_keeps_a_just_finished_interval() -> None:
    frames = parse_bars(_payload())
    now = datetime(2026, 8, 4, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert len(complete_bars(frames["AAPL"], now, bar_minutes=RANGE_BAR_MINUTES)) == 2


def test_the_gate_follows_the_resolution_it_is_given() -> None:
    """Design decision 5: the lane runs two resolutions at once — a 15-minute range and a
    1-minute trigger. The completeness gate must therefore take its interval from the
    caller. Judged as 1-minute bars, both rows above finished long ago; judged as
    15-minute bars at 09:52, the second one has not.
    """
    frames = parse_bars(_payload())
    now = datetime(2026, 8, 4, 9, 52, tzinfo=ZoneInfo("America/New_York"))
    assert len(complete_bars(frames["AAPL"], now, bar_minutes=TRIGGER_BAR_MINUTES)) == 2
    assert len(complete_bars(frames["AAPL"], now, bar_minutes=RANGE_BAR_MINUTES)) == 1


def test_complete_bars_on_an_empty_frame_is_empty_not_an_error() -> None:
    frames = parse_bars(_payload())
    empty = frames["AAPL"].iloc[:0]
    now = datetime(2026, 8, 4, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert complete_bars(empty, now, bar_minutes=TRIGGER_BAR_MINUTES).empty
