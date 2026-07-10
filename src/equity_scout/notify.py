"""Notification rules + orchestration: watchlist -> inbox pitches -> Telegram.

Selection is deliberately strict (spec §6: notify ONLY when genuinely attractive):
in_zone AND composite >= threshold AND ticker outside its cooldown window.
Cooldown compares ISO-8601 strings via date arithmetic (timezone-aware).
The send seam is (pitch_id, text) -> telegram_message_id so tests and the
no-token dry mode never touch the network; send=None records inbox rows only.
A NULL telegram_message_id means "no sender configured OR the send failed" —
either way the pitch lives in the inbox (source of truth), and the next run
re-qualifies the ticker once its cooldown has elapsed.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime, timedelta

from equity_scout.evidence.aggregate import build_alert_text, select_evidence_alerts
from equity_scout.evidence.storage import last_alert_at, record_alert, set_alert_message_id
from equity_scout.fundamentals import Fundamentals, fetch_fundamentals
from equity_scout.inbox_storage import create_pitch, last_pitch_at as _last_pitch_at
from equity_scout.inbox_storage import set_message_id
from equity_scout.telegram_client import TelegramError

DEFAULT_THRESHOLD = 0.45
DEFAULT_COOLDOWN_DAYS = 7
# Alerts re-fire slower than pitches: the underlying facts (a quarter's 13F, a filed
# congress purchase) do not change within days, they only accumulate.
DEFAULT_ALERT_COOLDOWN_DAYS = 14


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
    build: Callable[[dict, Fundamentals | None], str],
    send: Callable[[int, str], int] | None,
    enrich: Callable[[str], Fundamentals] | None = fetch_fundamentals,
    threshold: float = DEFAULT_THRESHOLD,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    now: str,
) -> int:
    """Create inbox pitches (and send them, if a sender is configured).

    Returns the number of pitches created. Each candidate's fundamentals are fetched
    once via `enrich` (default the live yfinance seam; `None` to skip) and passed to
    the pitch builder. The inbox row is written BEFORE the send so a Telegram failure
    can never lose a pitch — the dashboard inbox is the source of truth; Telegram is a
    delivery channel. A failed send is warned to stderr and the batch CONTINUES: one
    bad candidate must not silence the rest.
    """
    candidates = select_candidates(
        watchlist,
        last_pitch_at=lambda ticker: _last_pitch_at(db_path, ticker),
        threshold=threshold,
        cooldown_days=cooldown_days,
        now=now,
    )
    watchlist_id = watchlist.get("watchlist_id")  # top-level snapshot id from radar_storage
    for entry in candidates:
        fundamentals = enrich(entry["ticker"]) if enrich is not None else None
        text = build(entry, fundamentals)
        pitch_id = create_pitch(
            db_path,
            ticker=entry["ticker"],
            watchlist_id=watchlist_id,
            price=entry["price"],
            composite=entry["composite"],
            zone_low=entry["entry_zone_low"],
            zone_high=entry["entry_zone_high"],
            pitch=text,
            created_at=now,
        )
        if send is not None:
            try:
                set_message_id(db_path, pitch_id, send(pitch_id, text))
            except TelegramError as err:
                print(
                    f"Warnung: Telegram-Versand für {entry['ticker']} fehlgeschlagen: {err}",
                    file=sys.stderr,
                )
    return len(candidates)


def send_evidence_alerts(
    db_path: str,
    clusters: dict[str, list[dict]],
    *,
    send: Callable[[str], int] | None,
    cooldown_days: int = DEFAULT_ALERT_COOLDOWN_DAYS,
    now: str,
) -> int:
    """Off-watchlist evidence clusters -> evidence_alerts rows -> plain Telegram texts.

    Mirrors notify_watchlist's contract: the alert row is recorded BEFORE the send so a
    Telegram failure never loses an alert, a failed send warns and the batch continues,
    and send=None (no config / dry-run) records rows only. Alerts carry NO decision
    keyboard — they ask for a look, they never enter the arena's decision lanes.
    Returns the number of alerts recorded (sent or not).
    """
    recorded = 0
    for alert in select_evidence_alerts(clusters):
        ticker = alert["ticker"]
        if _inside_cooldown(last_alert_at(db_path, ticker), now, cooldown_days):
            continue
        text = build_alert_text(alert)
        alert_id = record_alert(
            db_path,
            ticker=ticker,
            reasons=alert["reasons"],
            text=text,
            telegram_message_id=None,
            now=now,
        )
        recorded += 1
        if send is not None:
            try:
                set_alert_message_id(db_path, alert_id, send(text))
            except TelegramError as err:
                print(
                    f"Warnung: Telegram-Versand für Evidenz-Alarm {ticker} fehlgeschlagen: {err}",
                    file=sys.stderr,
                )
    return recorded
