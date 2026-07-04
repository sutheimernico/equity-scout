"""Telegram client tests — pure logic + DI'd transport, no network.

Exception: the two _api error tests monkeypatch urllib.request.urlopen with canned
responses — _api IS the transport, so this is the one sanctioned stdlib patch.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from equity_scout.telegram_client import (
    TelegramError,
    build_decision_keyboard,
    extract_decision,
    load_telegram_config,
    poll_updates,
    send_message,
)

CHAT_ID = 4242


def _update(update_id: int, data: str, from_id: int = CHAT_ID) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {"id": f"cb{update_id}", "from": {"id": from_id}, "data": data},
    }


def test_build_decision_keyboard_has_three_action_buttons():
    kb = build_decision_keyboard(7)
    buttons = kb["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == ["buy:7", "pass:7", "later:7"]
    assert "Kaufen" in buttons[0]["text"]


def test_extract_decision_accepts_valid_actions_only():
    assert extract_decision(_update(1, "buy:7"), CHAT_ID) == ("buy", 7, "cb1")
    assert extract_decision(_update(2, "explode:7"), CHAT_ID) is None
    assert extract_decision(_update(3, "buy:notanint"), CHAT_ID) is None
    assert extract_decision({"update_id": 4}, CHAT_ID) is None


def test_extract_decision_rejects_wrong_sender():
    assert extract_decision(_update(1, "buy:7", from_id=999), CHAT_ID) is None


def test_extract_decision_rejects_boundary_payloads():
    assert extract_decision(_update(5, "buy:"), CHAT_ID) is None
    assert extract_decision(_update(6, "buy:7:extra"), CHAT_ID) is None
    assert extract_decision(_update(7, "buy:-7"), CHAT_ID) is None


def test_poll_updates_advances_offset_over_all_updates():
    batches = [[_update(10, "buy:1"), _update(11, "nonsense")], []]
    calls: list[int | None] = []

    def fake_get_updates(offset):
        calls.append(offset)
        return batches.pop(0) if batches else []

    decisions, offset = poll_updates(fake_get_updates, offset=None, chat_id=CHAT_ID)
    assert decisions == [("buy", 1, "cb10")]
    assert offset == 12  # advanced past BOTH updates, including the non-matching one
    assert calls == [None]


def test_load_telegram_config_fail_safe(capsys):
    assert load_telegram_config({}) is None
    assert (
        load_telegram_config({"COPILOT_TG_BOT_TOKEN": "t", "COPILOT_TG_CHAT_ID": "x"}) is None
    )
    assert "COPILOT_TG_CHAT_ID" in capsys.readouterr().err
    cfg = load_telegram_config({"COPILOT_TG_BOT_TOKEN": "t", "COPILOT_TG_CHAT_ID": "42"})
    assert cfg == {"token": "t", "chat_id": 42}


def test_api_raises_telegram_error_on_ok_false(monkeypatch):
    body = json.dumps({"ok": False, "description": "Bad Request: chat not found"}).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: io.BytesIO(body))
    with pytest.raises(TelegramError, match="chat not found"):
        send_message("token", CHAT_ID, "hallo")


def test_api_raises_telegram_error_with_http_error_body(monkeypatch):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(
            "https://api.telegram.org/botX/sendMessage",
            403,
            "Forbidden",
            None,
            io.BytesIO(b'{"ok":false,"description":"Forbidden: bot was blocked by the user"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(TelegramError, match="bot was blocked"):
        send_message("token", CHAT_ID, "hallo")
