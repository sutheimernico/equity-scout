"""Notify CLI: latest watchlist -> inbox pitches -> Telegram (if configured).

Usage:
    python scripts/run_notify.py [--db equity_scout.db] [--threshold 0.45]
        [--cooldown-days 7] [--dry-run]

Without COPILOT_TG_BOT_TOKEN/COPILOT_TG_CHAT_ID (or with --dry-run) pitches are
only written to the inbox — nothing is sent. Run scripts/run_radar.py first.

Pitches for watchlist candidates are annotated with external evidence (congress /
13F / news themes) from the trailing window; evidence clusters on OFF-watchlist
tickers go out as separately labelled evidence alerts (no decision buttons).
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.evidence.aggregate import attach_track_records
from equity_scout.evidence.person_storage import person_score_index
from equity_scout.evidence.storage import events_in_window
from equity_scout.fundamentals import fetch_fundamentals
from equity_scout.notify import (
    DEFAULT_COOLDOWN_DAYS,
    DEFAULT_THRESHOLD,
    notify_watchlist,
    send_evidence_alerts,
)
from equity_scout.pitch import build_pitch
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.telegram_client import (
    build_decision_keyboard,
    load_telegram_config,
    send_message,
)

# Congress filings arrive up to 45 days late; a 30-day window over EVENT dates keeps
# the pitch block about recent facts while the delay note carries the honesty context.
EVIDENCE_WINDOW_DAYS = 30


def _telegram_sender(config: dict) -> Callable[[int, str], int]:
    """Bind the resolved config into the (pitch_id, text) -> message_id send seam."""

    def send(pitch_id: int, text: str) -> int:
        return send_message(
            config["token"], config["chat_id"], text, build_decision_keyboard(pitch_id)
        )

    return send


def _alert_sender(config: dict) -> Callable[[str], int]:
    """Alerts go out WITHOUT a decision keyboard — they are not screener pitches."""

    def send(text: str) -> int:
        return send_message(config["token"], config["chat_id"], text, None)

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
        alert_send = None
        print("Telegram not configured — writing inbox pitches only.")
    else:
        send = _telegram_sender(config)
        alert_send = _alert_sender(config)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    watchlist_tickers = [entry["ticker"] for entry in watchlist.get("entries", [])]
    # Measured person scores (weekly run_person_scores refresh) annotate both surfaces.
    score_index = person_score_index(args.db)
    evidence_by_ticker = attach_track_records(
        events_in_window(
            args.db, window_days=EVIDENCE_WINDOW_DAYS, now=now, tickers=watchlist_tickers
        ),
        score_index,
    )

    def build(entry: dict, fundamentals) -> str:
        return build_pitch(
            entry, fundamentals, evidence=evidence_by_ticker.get(entry["ticker"])
        )

    count = notify_watchlist(
        args.db, watchlist, build=build, send=send, enrich=fetch_fundamentals,
        threshold=args.threshold, cooldown_days=args.cooldown_days, now=now,
    )
    print(f"Pitches created: {count}.")

    off_watchlist = attach_track_records(
        events_in_window(
            args.db, window_days=EVIDENCE_WINDOW_DAYS, now=now,
            exclude_tickers=watchlist_tickers,
        ),
        score_index,
    )
    alerts = send_evidence_alerts(args.db, off_watchlist, send=alert_send, now=now)
    print(f"Evidenz-Alarme: {alerts}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
