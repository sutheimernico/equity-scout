"""Market-window guard for the intraday chain — computed in America/New_York (v12 R10):
the fixed Berlin slot used to miss the first ~30 session minutes during the weeks when the
US has switched to DST but Europe has not (2026: Mar 8 vs Mar 29)."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from equity_scout.market_hours import last_completed_us_session, within_market_window

BERLIN = ZoneInfo("Europe/Berlin")


def berlin(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=BERLIN)


def test_inside_window_on_a_weekday():
    assert within_market_window(berlin(2026, 7, 14, 16, 0)) is True  # Tuesday, 10:00 ET


def test_window_follows_the_nyse_session_not_a_berlin_slot():
    # July: Berlin is CEST, NYSE session = 15:30-22:00 Berlin (+50 min settle grace since
    # 2026-08-04, sized to include the 16:45 ET cron slot).
    assert within_market_window(berlin(2026, 7, 14, 15, 29)) is False  # pre-open
    assert within_market_window(berlin(2026, 7, 14, 15, 30)) is True  # 09:30 ET open
    assert within_market_window(berlin(2026, 7, 14, 22, 50)) is True  # 16:50 ET grace end
    assert within_market_window(berlin(2026, 7, 14, 22, 51)) is False


def test_dst_transition_weeks_cover_the_real_open():
    # 2026-03-18: US already on EDT, Europe still on CET -> NYSE opens 14:30 Berlin.
    assert within_market_window(berlin(2026, 3, 18, 14, 35)) is True
    assert within_market_window(berlin(2026, 3, 18, 14, 25)) is False
    assert within_market_window(berlin(2026, 3, 18, 21, 25)) is True  # 16:25 ET, grace
    assert within_market_window(berlin(2026, 3, 18, 21, 55)) is False  # 16:55 ET


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


def test_last_completed_session_at_the_nightly_chain_slot():
    # 02:35 Berlin on Friday = 20:35 ET Thursday -> Thursday's session is complete.
    assert last_completed_us_session(berlin(2026, 7, 24, 2, 35)) == date(2026, 7, 23)


def test_last_completed_session_weekend_rolls_back_to_friday():
    assert last_completed_us_session(berlin(2026, 7, 25, 2, 35)) == date(2026, 7, 24)  # Sat
    assert last_completed_us_session(berlin(2026, 7, 26, 16, 0)) == date(2026, 7, 24)  # Sun
    # Monday 02:35 Berlin is still Sunday evening in New York -> Friday.
    assert last_completed_us_session(berlin(2026, 7, 27, 2, 35)) == date(2026, 7, 24)


def test_last_completed_session_mid_session_is_the_prior_day():
    # Live incident 2026-07-23 15:57 Berlin (09:57 ET, US mid-session): the chain booked
    # intraday prices as that day's close. The completed session was Wednesday's.
    assert last_completed_us_session(berlin(2026, 7, 23, 15, 57)) == date(2026, 7, 22)


def test_last_completed_session_flips_after_close_plus_grace():
    assert last_completed_us_session(berlin(2026, 7, 23, 22, 50)) == date(2026, 7, 22)  # 16:50 ET
    assert last_completed_us_session(berlin(2026, 7, 23, 22, 51)) == date(2026, 7, 23)  # 16:51 ET


def test_last_completed_session_rejects_naive_datetime():
    with pytest.raises(ValueError):
        last_completed_us_session(datetime(2026, 7, 24, 2, 35))


NEW_YORK = ZoneInfo("America/New_York")


def new_york(y, m, d, hh, mm, ss=0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=NEW_YORK)


def test_window_covers_a_cron_slot_after_the_last_bar_settles():
    """Regression, measured 2026-08-04: the last session bar starts 15:45 ET and is only
    settled at 16:20 (+15 bar +20 delay margin). The window used to close at 16:30:00 while
    the */15 cron fires at 16:30:0X — so NO run ever saw that bar inside the session, and
    st_session's force-flat never executed once in 15 recorded session exits. The window
    must reach past the 16:45 slot for the flat-by-close rule to be reachable at all."""
    assert within_market_window(new_york(2026, 8, 4, 16, 45, 3)) is True


def test_window_closes_before_the_following_cron_slot():
    """The counterweight: it must not creep so far that the 17:00 run also fires, which
    would poll a closed market for another hour."""
    assert within_market_window(new_york(2026, 8, 4, 17, 0, 3)) is False


def test_panel_cutoff_never_treats_a_just_closed_session_as_complete():
    """WINDOW_END also drives last_completed_us_session. Widening it may only make the
    panel MORE conservative — never let a still-settling session count as an end-of-day
    close (the 2026-07-23 incident)."""
    assert last_completed_us_session(new_york(2026, 8, 4, 16, 40)) == date(2026, 8, 3)
