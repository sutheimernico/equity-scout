"""Generic Telegram Bot API client for the copilot inbox.

Lifted from tap-approve's proven primitives (stdlib urllib, no dependencies) and
generalized from allow/deny to the buy/pass/later action set. Design rules kept:
- transport is a thin function; all logic is pure and takes injected callables
- fail-safe config: missing/malformed env yields None + stderr hint, never a crash
- the receiver consumes EVERY update's offset, matching or not, so stale button
  presses can't wedge the queue
Plain text messages only (no parse_mode), so no escaping is needed.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable

API = "https://api.telegram.org/bot{token}/{method}"
ACTIONS = ("buy", "pass", "later")
# Single source for the German action labels — buttons, receiver acks, and message
# edits must all render the same wording.
DECISION_LABELS = {"buy": "✅ Kaufen", "pass": "❌ Ablehnen", "later": "⏸ Später"}


class TelegramError(RuntimeError):
    """Bot API failure with Telegram's actual reason (HTTP error body or ok=false description)."""


def _optional_chat_id(env: dict, key: str, fallback: int) -> int:
    """Optional per-stream chat id; unset or malformed falls back to the main chat so a
    partial config degrades to today's single-chat behavior instead of losing messages."""
    raw = env.get(key)
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        print(f"{key} is not an integer — falling back to COPILOT_TG_CHAT_ID.", file=sys.stderr)
        return fallback


def load_telegram_config(env: dict) -> dict | None:
    """{"token", "chat_id", "intraday_chat_id", "daily_chat_id"} or None if unusable.

    chat_id is Nico's private chat (= his user id): the button-press security gate and the
    fallback for both streams. intraday: pitches + evidence alerts (the trading timeline);
    daily: the digest. Both may be group/channel ids the bot is a member of.
    """
    token = env.get("COPILOT_TG_BOT_TOKEN")
    raw_chat = env.get("COPILOT_TG_CHAT_ID")
    if not token or not raw_chat:
        return None
    try:
        chat_id = int(raw_chat)
    except ValueError:
        print("COPILOT_TG_CHAT_ID is not an integer — Telegram disabled.", file=sys.stderr)
        return None
    return {
        "token": token,
        "chat_id": chat_id,
        "intraday_chat_id": _optional_chat_id(env, "COPILOT_TG_CHAT_ID_INTRADAY", chat_id),
        "daily_chat_id": _optional_chat_id(env, "COPILOT_TG_CHAT_ID_DAILY", chat_id),
    }


def _api(token: str, method: str, params: dict, timeout: float = 35.0) -> dict:
    """Single POST to the Bot API. No retry — callers decide what failure means.

    Raises TelegramError with Telegram's own reason: HTTP errors carry it in the
    response body, and the API also reports failures as 200 + {"ok": false}.
    """
    request = urllib.request.Request(
        API.format(token=token, method=method),
        data=json.dumps(params).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise TelegramError(f"{method} failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        # DNS/connection failures have no HTTP response; wrap them too so callers'
        # TelegramError handling covers offline/unreachable states.
        raise TelegramError(f"{method} failed: {exc.reason}") from exc
    if not payload.get("ok"):
        raise TelegramError(f"{method} failed: {payload.get('description', 'unknown')}")
    return payload


def build_decision_keyboard(pitch_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": DECISION_LABELS[action], "callback_data": f"{action}:{pitch_id}"}
                for action in ACTIONS
            ]
        ]
    }


def send_message(token: str, chat_id: int, text: str, keyboard: dict | None = None) -> int:
    """Returns the Telegram message_id (stored so the receiver can edit later)."""
    params: dict = {"chat_id": chat_id, "text": text}
    if keyboard is not None:
        params["reply_markup"] = keyboard
    return int(_api(token, "sendMessage", params)["result"]["message_id"])


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Telegram caps sendMessage at 4096 chars; split at line boundaries (hard-split a
    single over-long line) so a long daily digest arrives complete instead of erroring."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # a single line longer than the cap: hard split
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def send_long_message(token: str, chat_id: int, text: str) -> int:
    """send_message per chunk, in order; returns the LAST message_id."""
    message_id = 0
    for chunk in split_message(text):
        message_id = send_message(token, chat_id, chunk)
    return message_id


def build_multipart(
    fields: dict[str, str], file_field: str, filename: str, blob: bytes, boundary: str
) -> tuple[bytes, str]:
    """multipart/form-data body + content type, stdlib-only (no requests dependency).
    Pure so the encoding is unit-testable without the network."""
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode("utf-8")
    )
    parts.append(blob)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def send_photo(
    token: str, chat_id: int, png: bytes, caption: str, keyboard: dict | None = None
) -> int:
    """sendPhoto with caption (cap: 1024 UTF-16 units — the caption builder enforces it)
    and optional decision keyboard. Returns the message_id."""
    import uuid

    fields: dict[str, str] = {"chat_id": str(chat_id), "caption": caption}
    if keyboard is not None:
        fields["reply_markup"] = json.dumps(keyboard)
    body, content_type = build_multipart(fields, "photo", "chart.png", png, uuid.uuid4().hex)
    request = urllib.request.Request(
        API.format(token=token, method="sendPhoto"),
        data=body, headers={"Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise TelegramError(
            f"sendPhoto failed with HTTP {exc.code}: "
            f"{exc.read().decode('utf-8', errors='replace')}"
        ) from exc
    except urllib.error.URLError as exc:
        raise TelegramError(f"sendPhoto failed: {exc.reason}") from exc
    if not payload.get("ok"):
        raise TelegramError(f"sendPhoto failed: {payload.get('description', 'unknown')}")
    return int(payload["result"]["message_id"])


def edit_message(token: str, chat_id: int, message_id: int, text: str) -> None:
    _api(token, "editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text})


def edit_caption(token: str, chat_id: int, message_id: int, caption: str) -> None:
    _api(token, "editMessageCaption",
         {"chat_id": chat_id, "message_id": message_id, "caption": caption})


def edit_pitch_outcome(
    edit_text: Callable[[int, str], None],
    edit_photo_caption: Callable[[int, str], None],
    message_id: int,
    text: str,
) -> None:
    """Write the decision outcome onto the original message, whatever its type: text
    pitches take the full outcome text; photo pitches (chart + caption, since the
    2026-07-15 redesign) reject editMessageText, so fall back to a short caption
    (header + decision line, capped for the 1024-unit caption limit). An unchanged
    message ("message is not modified") counts as success — the self-heal path
    re-attempts edits idempotently."""
    try:
        edit_text(message_id, text)
        return
    except TelegramError as exc:
        if "not modified" in str(exc).lower():
            return
    lines = text.splitlines()
    short = "\n".join([lines[0], lines[-1]]) if len(lines) > 1 else text
    edit_photo_caption(message_id, short[:980])


def answer_callback(token: str, callback_query_id: str, text: str) -> None:
    _api(token, "answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})


def get_updates(token: str, offset: int | None, long_poll: int = 20) -> list[dict]:
    params: dict = {"timeout": long_poll, "allowed_updates": ["callback_query"]}
    if offset is not None:
        params["offset"] = offset
    return _api(token, "getUpdates", params, timeout=long_poll + 5)["result"]


def extract_decision(update: dict, chat_id: int) -> tuple[str, int, str] | None:
    """(action, pitch_id, callback_query_id) — or None for anything not a valid,
    same-chat buy/pass/later press. The sender check is the security gate."""
    cq = update.get("callback_query")
    if not cq or cq.get("from", {}).get("id") != chat_id:
        return None
    action, _, raw_id = str(cq.get("data", "")).partition(":")
    if action not in ACTIONS:
        return None
    try:
        pitch_id = int(raw_id)
    except ValueError:
        return None
    if pitch_id < 0:
        return None
    return action, pitch_id, str(cq.get("id", ""))


def poll_updates(
    fetch: Callable[[int | None], list[dict]], offset: int | None, chat_id: int
) -> tuple[list[tuple[str, int, str]], int | None]:
    """One fetch round: returns (decisions, next_offset). Consumes every update."""
    decisions: list[tuple[str, int, str]] = []
    for update in fetch(offset):
        update_id = update.get("update_id")
        if update_id is None:
            continue
        offset = int(update_id) + 1
        decision = extract_decision(update, chat_id)
        if decision is not None:
            decisions.append(decision)
    return decisions, offset
