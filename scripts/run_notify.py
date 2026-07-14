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
from equity_scout.charts import fetch_year_closes, render_year_chart, year_return
from equity_scout.pitch import build_pitch, build_pitch_caption
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.telegram_client import (
    build_decision_keyboard,
    load_telegram_config,
    send_message,
    send_photo,
)

# Congress filings arrive up to 45 days late; a 30-day window over EVENT dates keeps
# the pitch block about recent facts while the delay note carries the honesty context.
EVIDENCE_WINDOW_DAYS = 30


def _telegram_sender(
    config: dict, evidence_by_ticker: dict[str, list[dict]]
) -> Callable[[int, str, dict, object], int]:
    """Send seam: chart-photo pitch with a compact sectioned caption (2026-07-15 redesign
    — Nico: kurz, klar sektioniert, mit 1-Jahres-Chart). Any chart/photo failure falls
    back to the classic long text message so a pitch is never lost to matplotlib or a
    missing price history. The inbox always keeps the long text."""
    chat_id = config.get("intraday_chat_id", config["chat_id"])

    def send(pitch_id: int, text: str, entry: dict, fundamentals) -> int:
        keyboard = build_decision_keyboard(pitch_id)
        try:
            dates, closes = fetch_year_closes(entry["ticker"])
            caption = build_pitch_caption(
                entry, fundamentals, evidence=evidence_by_ticker.get(entry["ticker"]),
                one_year_return=year_return(closes),
            )
            png = render_year_chart(entry["ticker"], dates, closes)
            return send_photo(config["token"], chat_id, png, caption, keyboard)
        except Exception as exc:  # noqa: BLE001 - photo path is best-effort by design
            print(f"Hinweis: Chart-Pitch für {entry['ticker']} nicht möglich ({exc}) — "
                  "sende Text-Pitch.", file=sys.stderr)
            return send_message(config["token"], chat_id, text, keyboard)

    return send


def _alert_sender(config: dict) -> Callable[[str], int]:
    """Alerts go out WITHOUT a decision keyboard — they are not screener pitches."""
    chat_id = config.get("intraday_chat_id", config["chat_id"])

    def send(text: str) -> int:
        return send_message(config["token"], chat_id, text, None)

    return send


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--cooldown-days", type=int, default=DEFAULT_COOLDOWN_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--inbox-only", action="store_true",
                        help="Record pitches/alerts in the inbox but send nothing to Telegram "
                             "(the 15-min chain uses this — Nico wants only the daily summary "
                             "on the phone; the timeline lives in the dashboard).")
    args = parser.parse_args()

    watchlist = load_latest_watchlist(args.db)
    if watchlist is None:
        print("No watchlist found — run scripts/run_radar.py first.", file=sys.stderr)
        return 1

    config = (
        None if (args.dry_run or args.inbox_only) else load_telegram_config(dict(os.environ))
    )

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

    if config is None:
        send = None
        alert_send = None
        print("Telegram not configured — writing inbox pitches only.")
    else:
        send = _telegram_sender(config, evidence_by_ticker)
        alert_send = _alert_sender(config)

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
