"""Market-window guard for the intraday chain — computed in America/New_York (v12 R10):
the fixed Berlin slot used to miss the first ~30 session minutes during the weeks when the
US has switched to DST but Europe has not (2026: Mar 8 vs Mar 29)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from equity_scout.market_hours import within_market_window

BERLIN = ZoneInfo("Europe/Berlin")


def berlin(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=BERLIN)


def test_inside_window_on_a_weekday():
    assert within_market_window(berlin(2026, 7, 14, 16, 0)) is True  # Tuesday, 10:00 ET


def test_window_follows_the_nyse_session_not_a_berlin_slot():
    # July: Berlin is CEST, NYSE session = 15:30-22:00 Berlin (+30 min settle grace).
    assert within_market_window(berlin(2026, 7, 14, 15, 29)) is False  # pre-open
    assert within_market_window(berlin(2026, 7, 14, 15, 30)) is True  # 09:30 ET open
    assert within_market_window(berlin(2026, 7, 14, 22, 30)) is True  # 16:30 ET grace end
    assert within_market_window(berlin(2026, 7, 14, 22, 31)) is False


def test_dst_transition_weeks_cover_the_real_open():
    # 2026-03-18: US already on EDT, Europe still on CET -> NYSE opens 14:30 Berlin.
    assert within_market_window(berlin(2026, 3, 18, 14, 35)) is True
    assert within_market_window(berlin(2026, 3, 18, 14, 25)) is False
    assert within_market_window(berlin(2026, 3, 18, 21, 25)) is True  # 16:25 ET, grace
    assert within_market_window(berlin(2026, 3, 18, 21, 35)) is False  # 16:35 ET


def test_weekend_is_always_outside():
    assert within_market_window(berlin(2026, 7, 18, 16, 0)) is False  # Saturday
    assert within_market_window(berlin(2026, 7, 19, 16, 0)) is False  # Sunday


def test_utc_input_is_converted():
    # 14:30 UTC in July = 10:30 ET -> inside.
    utc = datetime(2026, 7, 14, 14, 30, tzinfo=ZoneInfo("UTC"))
    assert within_market_window(utc) is True


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        within_market_window(datetime(2026, 7, 14, 16, 0))
