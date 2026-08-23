"""US-market window guard for the intraday copilot chain.

Computed in America/New_York (v12 R10, review 2026-07-20): the NYSE session 09:30-16:00
plus a grace so the last DELAYED 15-minute bars still settle inside the window. The
previous fixed Berlin slot (15:00-22:30) missed the first ~30 session minutes during the
weeks when the US has switched to DST but Europe has not (US: 2nd Sunday in March, EU:
last Sunday). US market holidays are still NOT modelled: on a holiday the chain runs
against unchanged prices and books nothing new (every step is idempotent), which is
cheaper and simpler than a holiday-calendar dependency.

The grace was 30 minutes until 2026-08-04 and that was too short by one cron slot — see
the WINDOW_END comment. The lesson generalises: a window that ends between two cron slots
is a window no run ever observes.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MARKET_TZ = "America/New_York"
SESSION_START = time(9, 30)
# 16:00 close + 50 min. The grace is NOT sized by the data delay but by the cron grid: the
# final 15:45 bar only settles at 16:20, and a 16:30 end left no */15 slot in between (the
# 16:30 run starts at 16:30:0X, a second past the guard). Measured 2026-08-04: 0 of 15
# session exits came from the in-session force-flat — every one of them was swept hours
# later by the nightly chain. 16:50 keeps the 16:45 slot inside the window and still stops
# short of 17:00.
WINDOW_END = time(16, 50)
# The real bell, as opposed to WINDOW_END's cron grace. Only used to price an outage: a
# window that reaches past 16:00 costs nothing after it.
SESSION_END = time(16, 0)


def within_market_window(now: datetime) -> bool:
    """True iff `now` (tz-aware) falls inside the NYSE session (+grace), market time."""
    if now.tzinfo is None:
        raise ValueError("within_market_window needs a tz-aware datetime")
    local = now.astimezone(ZoneInfo(MARKET_TZ))
    if local.weekday() >= 5:  # Saturday/Sunday
        return False
    return SESSION_START <= local.time() <= WINDOW_END


def last_completed_us_session(now: datetime) -> date:
    """The date of the last NYSE session already past close (+settle grace) as of `now`.

    The honest upper bound for a daily panel's clock: a price row dated after this is an
    intraday reading of a still-running session somewhere on the globe (Tokyo trades at
    02:35 Berlin; a daytime manual run catches the US itself mid-session), not an
    end-of-day close. US market holidays are NOT modelled — the cutoff is an upper bound,
    and a holiday simply has no panel row to keep (same trade-off as the window guard)."""
    if now.tzinfo is None:
        raise ValueError("last_completed_us_session needs a tz-aware datetime")
    local = now.astimezone(ZoneInfo(MARKET_TZ))
    candidate = local.date()
    if local.weekday() >= 5 or local.time() <= WINDOW_END:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def session_minutes_between(start: datetime, end: datetime) -> int:
    """Regular-session minutes (09:30-16:00 ET, Mon-Fri) inside [start, end).

    What makes an outage expensive is not its length but how much of it the market was open
    for: eight hours across a Saturday cost nothing, ninety minutes on a Tuesday afternoon
    cost every exit the lanes would have taken. Without this number an alert can only say
    how long the box was away, which is the question nobody needs answered.

    US market holidays are NOT modelled (same trade-off as the rest of this module), so the
    result is an upper bound — it can name minutes the exchange was closed anyway.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("session_minutes_between needs tz-aware datetimes")
    tz = ZoneInfo(MARKET_TZ)
    begin, finish = sorted((start.astimezone(tz), end.astimezone(tz)))
    total = 0
    day = begin.date()
    while day <= finish.date():
        if day.weekday() < 5:
            open_at = datetime.combine(day, SESSION_START, tzinfo=tz)
            close_at = datetime.combine(day, SESSION_END, tzinfo=tz)
            overlap = min(finish, close_at) - max(begin, open_at)
            if overlap > timedelta(0):
                total += int(overlap.total_seconds() // 60)
        day += timedelta(days=1)
    return total
