"""Market-window guard for the 30-minute intraday chain — pure function, Berlin time."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from equity_scout.market_hours import within_market_window

BERLIN = ZoneInfo("Europe/Berlin")


def berlin(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=BERLIN)


def test_inside_window_on_a_weekday():
    assert within_market_window(berlin(2026, 7, 14, 16, 0)) is True  # Tuesday afternoon


def test_window_edges_are_inclusive():
    assert within_market_window(berlin(2026, 7, 14, 15, 0)) is True
    assert within_market_window(berlin(2026, 7, 14, 22, 30)) is True
    assert within_market_window(berlin(2026, 7, 14, 14, 59)) is False
    assert within_market_window(berlin(2026, 7, 14, 22, 31)) is False


def test_weekend_is_always_outside():
    assert within_market_window(berlin(2026, 7, 18, 16, 0)) is False  # Saturday
    assert within_market_window(berlin(2026, 7, 19, 16, 0)) is False  # Sunday


def test_utc_input_is_converted_to_berlin():
    # 14:30 UTC in July = 16:30 Berlin (CEST) -> inside.
    utc = datetime(2026, 7, 14, 14, 30, tzinfo=ZoneInfo("UTC"))
    assert within_market_window(utc) is True


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        within_market_window(datetime(2026, 7, 14, 16, 0))
