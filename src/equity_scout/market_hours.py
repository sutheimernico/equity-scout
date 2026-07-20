"""US-market window guard for the intraday copilot chain.

Computed in America/New_York (v12 R10, review 2026-07-20): the NYSE session 09:30-16:00
plus a 30-minute grace so the last DELAYED 15-minute bars still settle inside the window.
The previous fixed Berlin slot (15:00-22:30) missed the first ~30 session minutes during
the weeks when the US has switched to DST but Europe has not (US: 2nd Sunday in March,
EU: last Sunday). US market holidays are still NOT modelled: on a holiday the chain runs
against unchanged prices and books nothing new (every step is idempotent), which is
cheaper and simpler than a holiday-calendar dependency.
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

MARKET_TZ = "America/New_York"
SESSION_START = time(9, 30)
WINDOW_END = time(16, 30)  # 16:00 close + 30 min settle grace for the delayed final bars


def within_market_window(now: datetime) -> bool:
    """True iff `now` (tz-aware) falls inside the NYSE session (+grace), market time."""
    if now.tzinfo is None:
        raise ValueError("within_market_window needs a tz-aware datetime")
    local = now.astimezone(ZoneInfo(MARKET_TZ))
    if local.weekday() >= 5:  # Saturday/Sunday
        return False
    return SESSION_START <= local.time() <= WINDOW_END
