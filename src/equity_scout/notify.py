"""Notification rules + orchestration: watchlist -> inbox pitches -> Telegram.

Selection is deliberately strict (spec §6: notify ONLY when genuinely attractive):
in_zone AND composite >= threshold AND ticker outside its cooldown window.
Cooldown compares ISO-8601 strings via date arithmetic (timezone-aware).
The send seam is (pitch_id, text) -> telegram_message_id so tests and the
no-token dry mode never touch the network; send=None records inbox rows only.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from equity_scout.inbox_storage import create_pitch, last_pitch_at as _last_pitch_at
from equity_scout.inbox_storage import set_message_id

DEFAULT_THRESHOLD = 0.45
DEFAULT_COOLDOWN_DAYS = 7


def _inside_cooldown(last_iso: str | None, now_iso: str, cooldown_days: int) -> bool:
    if last_iso is None:
        return False
    last = datetime.fromisoformat(last_iso)
    now = datetime.fromisoformat(now_iso)
    return now - last < timedelta(days=cooldown_days)


def select_candidates(
    watchlist: dict,
    *,
    last_pitch_at: Callable[[str], str | None],
    threshold: float,
    cooldown_days: int,
    now: str,
) -> list[dict]:
    return [
        entry
        for entry in watchlist.get("entries", [])
        if entry["in_zone"]
        and entry["composite"] >= threshold
        and not _inside_cooldown(last_pitch_at(entry["ticker"]), now, cooldown_days)
    ]


def notify_watchlist(
    db_path: str,
    watchlist: dict,
    *,
    build: Callable[[dict], str],
    send: Callable[[int, str], int] | None,
    threshold: float = DEFAULT_THRESHOLD,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    now: str,
) -> int:
    """Create inbox pitches (and send them, if a sender is configured).

    Returns the number of pitches created. The inbox row is written BEFORE the
    send so a Telegram failure can never lose a pitch — the dashboard inbox is
    the source of truth; Telegram is a delivery channel.
    """
    candidates = select_candidates(
        watchlist,
        last_pitch_at=lambda ticker: _last_pitch_at(db_path, ticker),
        threshold=threshold,
        cooldown_days=cooldown_days,
        now=now,
    )
    for entry in candidates:
        text = build(entry)
        pitch_id = create_pitch(
            db_path,
            ticker=entry["ticker"],
            watchlist_id=entry.get("watchlist_id"),
            price=entry["price"],
            composite=entry["composite"],
            zone_low=entry["entry_zone_low"],
            zone_high=entry["entry_zone_high"],
            pitch=text,
            created_at=now,
        )
        if send is not None:
            set_message_id(db_path, pitch_id, send(pitch_id, text))
    return len(candidates)
