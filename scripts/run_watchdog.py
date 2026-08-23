"""CLI: dead-man watchdog step (v12 W1) — runs inside the 24/7 crypto cron slot.

Checks every chain heartbeat against its SLA and sends ONE Telegram warning per chain
per 24h cooldown. Without a configured Telegram bot it only prints — the digest's
staleness guards remain the fallback surface. See `equity_scout.watchdog`.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.state_storage import record_heartbeat
from equity_scout.telegram_client import TelegramError, load_telegram_config, send_message
from equity_scout.watchdog import (
    alerts_due,
    build_alert_text,
    build_gap_text,
    mark_alerted,
    overdue_chains,
    record_gap,
    scheduler_gap,
)


def _report(text: str) -> None:
    """Print, and send to Telegram when it is configured. No cooldown: a gap is detected on
    the first run back and never again, because the next run's predecessor is fresh."""
    print(text)
    tg_config = load_telegram_config(dict(os.environ))
    if tg_config is None:
        return
    try:
        send_message(
            tg_config["token"], tg_config.get("daily_chat_id", tg_config["chat_id"]), text
        )
    except TelegramError as err:
        print(f"Warnung: Watchdog-Meldung nicht zustellbar: {err}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    # BEFORE the heartbeat: the gap is measured against the previous run, and writing first
    # would measure zero. This is the only check that can see the scheduler itself missing.
    gap = scheduler_gap(args.db, now=now)
    record_heartbeat(args.db, "watchdog", now=now.isoformat())
    if gap is not None:
        record_gap(args.db, gap, now=now)
        _report(build_gap_text(gap))

    overdue = overdue_chains(args.db, now=now)
    if not overdue:
        print("Watchdog: alle Ketten am Leben.")
        return 0
    due = alerts_due(args.db, overdue, now=now)
    for item in overdue:
        print(f"Watchdog: {item['chain']} überfällig (seit {item['overdue_hours']:.0f} h).")
    if not due:
        print("Watchdog: Alarm bereits gesendet (Cooldown).")
        return 0

    text = build_alert_text(due)
    tg_config = load_telegram_config(dict(os.environ))
    if tg_config is None:
        print(text)
        return 0
    try:
        send_message(
            tg_config["token"], tg_config.get("daily_chat_id", tg_config["chat_id"]), text
        )
    except TelegramError as err:
        # Do NOT mark alerted — the next cycle retries.
        print(f"Warnung: Watchdog-Alarm nicht zustellbar: {err}", file=sys.stderr)
        return 0
    mark_alerted(args.db, [d["chain"] for d in due], now=now)
    print(f"Watchdog: Alarm gesendet ({', '.join(d['chain'] for d in due)}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
