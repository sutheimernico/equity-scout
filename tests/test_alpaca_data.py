"""Alpaca IEX bars must satisfy the exact contract intraday_bars.fetch_bars satisfies:
tz-aware America/New_York index, lowercase open/high/low/close columns. st_session.decide()
must not be able to tell the two feeds apart."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from equity_scout.alpaca_data import (
    RANGE_BAR_MINUTES,
    TRIGGER_BAR_MINUTES,
    AlpacaDataError,
    complete_bars,
    parse_bars,
    regular_session_bars,
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


NY = ZoneInfo("America/New_York")


def _frame(*stamps: str) -> pd.DataFrame:
    """Bars at the given New-York wall-clock times, one minute apart in intent."""
    index = pd.DatetimeIndex([pd.Timestamp(s, tz=NY) for s in stamps])
    return pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
        index=index,
    )


def test_regular_session_drops_the_premarket_prints() -> None:
    """The gate that keeps `opening_range` meaningful.

    yfinance handed the other feed a regular-session-only frame for free (period="1d",
    prepost off). Alpaca returns every print in the requested window, and `st_session
    .opening_range` takes the FIRST TWO BARS it is given — on a raw Alpaca frame that would
    be a 07:xx pre-market range, and every stop and target derives from it.
    """
    bars = _frame("2026-08-04 07:15", "2026-08-04 09:29", "2026-08-04 09:30",
                  "2026-08-04 09:31", "2026-08-04 16:00", "2026-08-04 18:30")
    kept = regular_session_bars(bars)
    assert [str(t.time()) for t in kept.index] == ["09:30:00", "09:31:00"]


def test_regular_session_keeps_one_day_only() -> None:
    """A multi-day window must not splice yesterday's tail onto today's opening range."""
    bars = _frame("2026-08-03 15:55", "2026-08-04 09:30", "2026-08-04 09:31")
    kept = regular_session_bars(bars)
    assert [str(t.date()) for t in kept.index] == ["2026-08-04", "2026-08-04"]


def test_regular_session_can_be_pinned_to_a_given_day() -> None:
    bars = _frame("2026-08-03 09:30", "2026-08-04 09:30")
    kept = regular_session_bars(bars, session_date=date(2026, 8, 3))
    assert [str(t.date()) for t in kept.index] == ["2026-08-03"]


def test_regular_session_on_an_empty_frame_is_empty_not_an_error() -> None:
    assert regular_session_bars(pd.DataFrame()).empty


def test_parse_latest_trades_maps_price_and_time_and_skips_empty() -> None:
    """Gap-fade lane: the pre-market signal is the LATEST IEX trade per ticker. A ticker
    that has not printed pre-market is ABSENT, never a zero — absence means no signal."""
    from datetime import datetime, timezone

    from equity_scout.alpaca_data import parse_latest_trades

    payload = {"trades": {
        "NVDA": {"t": "2026-08-17T13:22:05.123456Z", "p": 97.5, "s": 100},
        "GONE": {},
    }}
    trades = parse_latest_trades(payload)
    assert set(trades) == {"NVDA"}
    price, at = trades["NVDA"]
    assert price == 97.5
    assert at == datetime(2026, 8, 17, 13, 22, 5, 123456, tzinfo=timezone.utc)


def test_parse_latest_trades_rejects_a_contract_break() -> None:
    import pytest

    from equity_scout.alpaca_data import AlpacaDataError, parse_latest_trades

    with pytest.raises(AlpacaDataError):
        parse_latest_trades({"error": "forbidden"})
