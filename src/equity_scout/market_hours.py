"""Approximate US-market window guard for the intraday copilot chain.

The 30-minute intraday chain (plan v6 P5) only does useful work while US prices actually move.
The window is expressed in Europe/Berlin (Nico's cron timezone) as 15:00-22:30 Mon-Fri —
deliberately a bit WIDER than the NYSE session (15:30-22:00 CEST) so the DST-misalignment weeks
(US and EU switch on different dates) stay covered. US market holidays are NOT modelled: on a
holiday the chain runs against unchanged prices and books nothing new (every step is idempotent),
which is cheaper and simpler than a holiday calendar dependency.
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

WINDOW_TZ = "Europe/Berlin"
WINDOW_START = time(15, 0)
WINDOW_END = time(22, 30)


def within_market_window(now: datetime) -> bool:
    """True iff `now` (tz-aware) falls inside the approximate US trading window, Berlin time."""
    if now.tzinfo is None:
        raise ValueError("within_market_window needs a tz-aware datetime")
    local = now.astimezone(ZoneInfo(WINDOW_TZ))
    if local.weekday() >= 5:  # Saturday/Sunday
        return False
    return WINDOW_START <= local.time() <= WINDOW_END
