"""The 2026-07-21 outage rule, stated as code: whoever cannot show they were here a bar ago
does not open a new position. Exits stay allowed — abandoning an open position is worse
than any entry rule."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import scripts.run_shortterm as runner

NY = ZoneInfo("America/New_York")
may_open_new_position = runner.may_open_new_position


def test_a_run_one_cadence_after_the_last_one_may_open() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    last = (now - timedelta(minutes=1)).isoformat()
    assert may_open_new_position(last_run=last, now=now) is True


def test_a_gap_of_more_than_the_tolerance_blocks_new_entries() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    last = (now - timedelta(minutes=40)).isoformat()
    assert may_open_new_position(last_run=last, now=now) is False


def test_the_very_first_run_may_open() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    assert may_open_new_position(last_run=None, now=now) is True


def test_the_tolerance_is_the_callers_to_set() -> None:
    """The gate measures "did the machine miss slots", so its tolerance belongs to the
    cadence, not to the bar length. The lane runs every 15 minutes today and every minute
    after Task 9; the same gap must be readable as fine under one and as a gap under the
    other, which a hardcoded constant cannot express.
    """
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    last = (now - timedelta(minutes=12)).isoformat()
    assert may_open_new_position(last_run=last, now=now, max_gap=timedelta(minutes=22)) is True
    assert may_open_new_position(last_run=last, now=now, max_gap=timedelta(minutes=5)) is False


def test_the_default_tolerance_matches_the_one_minute_cadence() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    assert runner.MAX_RUN_GAP == timedelta(minutes=5)
    assert may_open_new_position(
        last_run=(now - timedelta(minutes=4, seconds=59)).isoformat(), now=now
    ) is True
    assert may_open_new_position(
        last_run=(now - timedelta(minutes=5, seconds=1)).isoformat(), now=now
    ) is False


def test_a_last_run_stamp_from_the_future_does_not_unlock_entries() -> None:
    """Clock skew or a repaired state file must not read as "we were just here". The
    2026-07-24 Tokyo-timestamp incident is precisely a future as_of slipping into state.
    """
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    ahead = (now + timedelta(hours=3)).isoformat()
    assert may_open_new_position(last_run=ahead, now=now) is False


# --- Task 9 Step 1: the quiet run ------------------------------------------------------


def test_a_run_that_changed_nothing_reports_nothing() -> None:
    """Prerequisite for the one-minute cadence. At */15 a report block per run is 26 lines
    a day and all of them worth reading; at * * * * * it is ~390, and that is how the two
    production bugs this project already hit stayed invisible in the log.
    """
    assert runner.session_report_due(fills=[], first_run_of_day=False) is False


def test_a_fill_is_always_reported() -> None:
    assert runner.session_report_due(fills=["a fill"], first_run_of_day=False) is True


def test_the_first_run_of_the_day_is_reported_even_without_fills() -> None:
    """One anchor line per session proves the lane ran at all — otherwise a lane that died
    at 09:30 and a lane that simply found no setup look identical in the log."""
    assert runner.session_report_due(fills=[], first_run_of_day=True) is True
