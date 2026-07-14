"""Digest CLI: inbox pitches -> daily German digest, delivered where configured.

Usage:
    python scripts/run_digest.py [--db equity_scout.db]

Delivery is additive and fail-safe: SMTP e-mail if SMTP_* env is set, Telegram
daily chat if COPILOT_TG_* env is set (channel split 2026-07-14), stdout when
neither is configured — an unconfigured digest is not an error.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.digest import build_digest, load_smtp_config, send_digest
from equity_scout.evidence.ledger import stats_by_source
from equity_scout.evidence.storage import load_alerts
from equity_scout.inbox_storage import load_pitches
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.telegram_client import (
    TelegramError,
    load_telegram_config,
    send_long_message,
)

OPPORTUNITY_TOP_N = 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    # limit=1000: don't let load_pitches' default cap (100) silently drop open pitches
    # from a DAILY digest; the decided section is scoped to the last 24h instead.
    pitches = load_pitches(args.db, limit=1000)
    now = datetime.now(timezone.utc)
    date_label = now.date().isoformat()
    day_ago = (now - timedelta(hours=24)).isoformat(timespec="seconds")

    alerts_today = [a for a in load_alerts(args.db, limit=50) if a["created_at"] >= day_ago]
    watchlist = load_latest_watchlist(args.db) or {}
    opportunities = sorted(
        watchlist.get("entries", []), key=lambda e: e["composite"], reverse=True
    )[:OPPORTUNITY_TOP_N]

    text = build_digest(
        pitches,
        date_label=date_label,
        decided_since=day_ago,
        evidence_stats=stats_by_source(args.db),
        alerts_today=alerts_today,
        opportunities=opportunities,
    )

    smtp_config = load_smtp_config(dict(os.environ))
    tg_config = load_telegram_config(dict(os.environ))
    if smtp_config is not None:
        send_digest(smtp_config, f"Copilot-Digest {date_label}", text)
    if tg_config is not None:
        try:
            send_long_message(
                tg_config["token"], tg_config.get("daily_chat_id", tg_config["chat_id"]), text
            )
        except TelegramError as err:
            print(f"Warnung: Telegram-Digest-Versand fehlgeschlagen: {err}", file=sys.stderr)
    if smtp_config is None and tg_config is None:
        print(text)
        print("Neither SMTP nor Telegram configured — printing digest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
