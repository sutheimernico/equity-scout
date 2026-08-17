"""Minute-bar store: paged parsing, session filter, on-disk roundtrip."""
import pandas as pd
import pytest

from equity_scout.data.minute_bars import (
    REGULAR_CLOSE_ET,
    REGULAR_OPEN_ET,
    bars_path,
    load_minutes,
    parse_bars_page,
    regular_session_only,
    save_year,
)

PAGE = {
    "bars": {
        "AAPL": [
            {"t": "2024-01-02T14:30:00Z", "o": 187.0, "h": 187.5, "l": 186.8,
             "c": 187.2, "v": 120000},
            {"t": "2024-01-02T14:31:00Z", "o": 187.2, "h": 187.4, "l": 187.0,
             "c": 187.1, "v": 90000},
        ]
    },
    "next_page_token": "abc",
}


def test_parse_bars_page_returns_utc_indexed_frame_and_token():
    frame, token = parse_bars_page(PAGE, "AAPL")
    assert token == "abc"
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 2
    assert str(frame.index.tz) == "UTC"
    assert frame["close"].iloc[-1] == 187.1


def test_parse_bars_page_absent_symbol_is_empty_not_error():
    frame, token = parse_bars_page({"bars": {}}, "AAPL")
    assert frame.empty and token is None


def test_regular_session_only_drops_pre_and_after_market():
    # 13:00Z = 08:00 ET (pre), 14:30Z = 09:30 ET (open), 21:00Z = 16:00 ET (close, exclusive)
    index = pd.to_datetime(
        ["2024-01-02T13:00:00Z", "2024-01-02T14:30:00Z",
         "2024-01-02T20:59:00Z", "2024-01-02T21:00:00Z"]
    )
    frame = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0]}, index=index)
    assert regular_session_only(frame)["close"].tolist() == [2.0, 3.0]


def test_session_filter_is_dst_correct():
    # January: 14:30Z = 09:30 ET (EST). July: 14:30Z = 10:30 ET, and 13:30Z = 09:30 ET (EDT).
    # A naive UTC-hour filter would drop the July open bar or keep a pre-market one.
    index = pd.to_datetime(["2024-07-02T13:30:00Z", "2024-07-02T12:30:00Z"])
    frame = pd.DataFrame({"close": [1.0, 2.0]}, index=index)
    assert regular_session_only(frame)["close"].tolist() == [1.0]


def test_regular_session_constants_are_the_us_cash_session():
    assert (REGULAR_OPEN_ET, REGULAR_CLOSE_ET) == ("09:30", "16:00")


def test_save_and_load_roundtrip(tmp_path):
    index = pd.to_datetime(["2024-01-02T14:30:00Z", "2024-01-02T14:31:00Z"])
    frame = pd.DataFrame(
        {"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0],
         "close": [1.0, 2.0], "volume": [10, 20]},
        index=index,
    )
    save_year(frame, "AAPL", 2024, root=tmp_path)
    assert bars_path("AAPL", 2024, root=tmp_path).exists()
    back = load_minutes(["AAPL"], years=[2024], root=tmp_path)["AAPL"]
    assert len(back) == 2
    assert str(back.index.tz) == "UTC"
    assert back["close"].tolist() == [1.0, 2.0]


def test_load_minutes_skips_missing_years_without_inventing_data(tmp_path):
    assert load_minutes(["AAPL"], years=[2024], root=tmp_path) == {}


def test_load_minutes_rejects_a_year_it_cannot_parse(tmp_path):
    path = bars_path("AAPL", 2024, root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not,a,bar,file\n1,2,3,4\n")
    with pytest.raises(ValueError, match="AAPL 2024"):
        load_minutes(["AAPL"], years=[2024], root=tmp_path)
