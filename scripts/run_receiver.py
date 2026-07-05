"""Decision receiver: long-polls Telegram for button presses, records them.

Usage:
    python scripts/run_receiver.py [--db equity_scout.db] [--rounds N]

Requires COPILOT_TG_BOT_TOKEN / COPILOT_TG_CHAT_ID. Runs until interrupted
(--rounds limits polling rounds, mainly for supervised runs). Decisions land in
the inbox (source of truth); the original message is edited with the outcome so
the Telegram thread reflects the decision. Duplicate/late presses are answered
politely and never overwrite an existing decision.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.inbox_storage import decide_pitch, load_pitches
from equity_scout.telegram_client import (
    answer_callback,
    edit_message,
    get_updates,
    load_telegram_config,
    poll_updates,
)

_DECISION_LABEL = {"buy": "✅ Kaufen", "pass": "❌ Ablehnen", "later": "⏸ Später"}


def _pitch_by_id(db_path: str, pitch_id: int) -> dict | None:
    # Linear scan over load_pitches — fine at personal scale (dozens of pitches,
    # not millions); revisit with a dedicated lookup if the inbox ever grows large.
    return next((p for p in load_pitches(db_path, limit=1000) if p["id"] == pitch_id), None)


def process_round(
    db_path: str,
    *,
    fetch: Callable[[int | None], list[dict]],
    chat_id: int,
    offset: int | None,
    answer: Callable[[str, str], None],
    edit: Callable[[int, str], None],
    now: str,
) -> int | None:
    """One polling round: apply decisions, ack buttons, edit messages."""
    decisions, offset = poll_updates(fetch, offset, chat_id)
    for action, pitch_id, callback_id in decisions:
        label = _DECISION_LABEL[action]
        if decide_pitch(db_path, pitch_id, action, decided_at=now):
            answer(callback_id, f"{label} vermerkt")
            pitch = _pitch_by_id(db_path, pitch_id)
            if pitch and pitch.get("telegram_message_id"):
                edit(
                    pitch["telegram_message_id"],
                    f"{pitch['pitch']}\n\n— Entscheidung: {label} ({now})",
                )
        else:
            answer(callback_id, "Bereits entschieden.")
    return offset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--rounds", type=int, default=None)
    args = parser.parse_args()

    config = load_telegram_config(dict(os.environ))
    if config is None:
        print("Telegram not configured — receiver cannot run.", file=sys.stderr)
        return 1
    token, chat_id = config["token"], config["chat_id"]

    offset: int | None = None
    rounds = 0
    print("Receiver läuft — Strg+C zum Beenden.")
    try:
        while args.rounds is None or rounds < args.rounds:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            offset = process_round(
                args.db,
                fetch=lambda off: get_updates(token, off),
                chat_id=chat_id,
                offset=offset,
                answer=lambda cb, text: answer_callback(token, cb, text),
                edit=lambda mid, text: edit_message(token, chat_id, mid, text),
                now=now,
            )
            rounds += 1
    except KeyboardInterrupt:
        print("Receiver beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
