"""Decision receiver: long-polls Telegram for button presses, records them.

Usage:
    python scripts/run_receiver.py [--db equity_scout.db] [--rounds N]

Requires COPILOT_TG_BOT_TOKEN / COPILOT_TG_CHAT_ID. Runs until interrupted
(--rounds limits polling rounds, mainly for supervised runs). Decisions land in
the inbox (source of truth); the original message is edited with the outcome so
the Telegram thread reflects the decision. Duplicate/late presses are answered
politely and never overwrite an existing decision.

Resilience: transient Telegram/network failures never kill the loop — a failed
round warns to stderr and retries after a short backoff. The update offset is
held in memory only (no persistence in v1): after a crash/restart Telegram
redelivers every unconfirmed update, and decide_pitch is idempotent (first
decision wins), so replaying updates is safe. A lost outcome-edit self-heals on
the next press of the same message: the already-decided branch re-attempts the
edit with the ORIGINAL decision and timestamp (Telegram no-ops via "message is
not modified" if it already went through).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.inbox_storage import decide_pitch, get_pitch
from equity_scout.telegram_client import (
    DECISION_LABELS,
    TelegramError,
    answer_callback,
    edit_caption,
    edit_message,
    edit_pitch_outcome,
    get_updates,
    load_telegram_config,
    poll_updates,
)


def _try_telegram(call: Callable, *args, what: str) -> None:
    """Acks and edits are best-effort: the DB decision is already safe, so a failed
    Telegram call is warned and skipped, never allowed to abort the round."""
    try:
        call(*args)
    except (TelegramError, OSError) as exc:
        print(f"Warnung: {what} fehlgeschlagen: {exc}", file=sys.stderr)


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
        if decide_pitch(db_path, pitch_id, action, decided_at=now):
            label = DECISION_LABELS[action]
            _try_telegram(answer, callback_id, f"{label} vermerkt", what="Telegram-Ack")
            pitch = get_pitch(db_path, pitch_id)
            if pitch and pitch.get("telegram_message_id"):
                text = f"{pitch['pitch']}\n\n— Entscheidung: {label} ({now})"
                _try_telegram(edit, pitch["telegram_message_id"], text, what="Telegram-Edit")
        else:
            _try_telegram(answer, callback_id, "Bereits entschieden.", what="Telegram-Ack")
            # Self-heal: if the outcome edit was lost earlier, re-attempt it with the
            # stored decision. Idempotent — an unchanged message is a Telegram no-op
            # error ("message is not modified"), swallowed by _try_telegram.
            pitch = get_pitch(db_path, pitch_id)
            if pitch and pitch["status"] != "open" and pitch.get("telegram_message_id"):
                label = DECISION_LABELS.get(pitch["status"], pitch["status"])
                text = f"{pitch['pitch']}\n\n— Entscheidung: {label} ({pitch['decided_at']})"
                _try_telegram(edit, pitch["telegram_message_id"], text, what="Telegram-Edit")
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
    # Pitches (and their outcome edits) live in the intraday chat since the channel split;
    # chat_id itself stays the button-press security gate (the pressing USER's id).
    pitch_chat_id = config.get("intraday_chat_id", chat_id)

    offset: int | None = None
    rounds = 0
    print("Receiver läuft — Strg+C zum Beenden.")
    try:
        while args.rounds is None or rounds < args.rounds:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            try:
                offset = process_round(
                    args.db,
                    fetch=lambda off: get_updates(token, off),
                    chat_id=chat_id,
                    offset=offset,
                    answer=lambda cb, text: answer_callback(token, cb, text),
                    # Photo pitches (chart + caption) reject editMessageText; the outcome
                    # helper falls back to a short caption edit for those.
                    edit=lambda mid, text: edit_pitch_outcome(
                        lambda m, t: edit_message(token, pitch_chat_id, m, t),
                        lambda m, c: edit_caption(token, pitch_chat_id, m, c),
                        mid, text,
                    ),
                    now=now,
                )
            except (TelegramError, OSError) as exc:
                # Transient network/API trouble: warn, back off, keep the loop alive.
                print(
                    f"Warnung: Polling-Runde fehlgeschlagen: {exc} — "
                    "nächster Versuch in 5 Sekunden.",
                    file=sys.stderr,
                )
                time.sleep(5)
            rounds += 1
    except KeyboardInterrupt:
        print("Receiver beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
