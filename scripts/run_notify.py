"""Notify CLI: latest watchlist -> inbox pitches -> Telegram (if configured).

Usage:
    python scripts/run_notify.py [--db equity_scout.db] [--threshold 0.45]
        [--cooldown-days 7] [--dry-run]

Without COPILOT_TG_BOT_TOKEN/COPILOT_TG_CHAT_ID (or with --dry-run) pitches are
only written to the inbox — nothing is sent. Run scripts/run_radar.py first.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.fundamentals import fetch_fundamentals
from equity_scout.notify import DEFAULT_COOLDOWN_DAYS, DEFAULT_THRESHOLD, notify_watchlist
from equity_scout.pitch import build_pitch
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.telegram_client import (
    build_decision_keyboard,
    load_telegram_config,
    send_message,
)


def _telegram_sender(config: dict) -> Callable[[int, str], int]:
    """Bind the resolved config into the (pitch_id, text) -> message_id send seam."""

    def send(pitch_id: int, text: str) -> int:
        return send_message(
            config["token"], config["chat_id"], text, build_decision_keyboard(pitch_id)
        )

    return send


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--cooldown-days", type=int, default=DEFAULT_COOLDOWN_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    watchlist = load_latest_watchlist(args.db)
    if watchlist is None:
        print("No watchlist found — run scripts/run_radar.py first.", file=sys.stderr)
        return 1

    config = None if args.dry_run else load_telegram_config(dict(os.environ))
    if config is None:
        send = None
        print("Telegram not configured — writing inbox pitches only.")
    else:
        send = _telegram_sender(config)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    count = notify_watchlist(
        args.db, watchlist, build=build_pitch, send=send, enrich=fetch_fundamentals,
        threshold=args.threshold, cooldown_days=args.cooldown_days, now=now,
    )
    print(f"Pitches created: {count}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
