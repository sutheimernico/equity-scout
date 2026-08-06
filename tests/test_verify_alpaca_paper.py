"""The density measurement that decides whether a 1-minute trigger is buildable.

Only the pure part is tested: the rest of the script talks to a live third-party API.
Density has now been mismeasured twice (after-hours tail on 2026-08-05, and the window
reaching back past the open on 2026-08-06), and both times the number condemned a feed that
was in fact fine — so the arithmetic gets a test even though the script around it does not.
"""
from __future__ import annotations

import scripts.verify_alpaca_paper as verify


def _bars(*stamps: str) -> list[dict]:
    """Bar rows in the shape the Alpaca data API returns them."""
    return [{"t": f"2026-08-06T{stamp}:00Z"} for stamp in stamps]


def _minutes(first: str, count: int) -> list[dict]:
    hour, minute = (int(part) for part in first.split(":"))
    start = hour * 60 + minute
    return _bars(*[f"{(start + i) // 60:02d}:{(start + i) % 60:02d}" for i in range(count)])


def test_full_hour_inside_the_session_is_complete():
    share, slots = verify._coverage(_minutes("19:00", 60))
    assert slots == 60
    assert share == 1.0


def test_window_is_capped_at_the_open_instead_of_scoring_a_short_session_as_thin():
    # 15 minutes after the open every minute printed; the missing 45 slots of the 60-minute
    # window are before 13:30Z and never could have carried a bar. Scoring that as 25 %
    # produced a false alarm on 2026-08-06.
    share, slots = verify._coverage(_minutes("13:30", 15))
    assert slots == 15
    assert share is None, "too little session history is 'not yet measurable', not 'thin'"


def test_half_hour_after_the_open_is_measurable_against_the_shorter_window():
    share, slots = verify._coverage(_minutes("13:30", 30))
    assert slots == 30
    assert share == 1.0


def test_real_holes_are_still_reported_as_thin():
    every_other = _bars(*[f"19:{minute:02d}" for minute in range(0, 60, 2)])
    share, slots = verify._coverage(every_other)
    assert slots == 60
    assert share == 0.5
    assert share is not None and share < verify.MIN_COVERAGE


def test_premarket_bars_do_not_pad_the_count():
    # Pre-market prints are thin and irrelevant: the lane only trades the regular session.
    share, slots = verify._coverage(_minutes("13:00", 30) + _minutes("13:30", 30))
    assert slots == 30
    assert share == 1.0


def test_no_session_bars_at_all_is_zero_not_unmeasurable():
    share, slots = verify._coverage(_minutes("12:00", 20))
    assert slots == 0
    assert share == 0.0
