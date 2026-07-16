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
    escape_html,
    extract_decision,
    load_telegram_config,
    poll_updates,
    send_message,
    strip_html,
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
    # Channel split (2026-07-14): both stream ids fall back to the main chat when unset.
    assert cfg == {"token": "t", "chat_id": 42,
                   "intraday_chat_id": 42, "daily_chat_id": 42}


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


def test_escape_html_covers_the_three_markup_chars():
    assert escape_html("Barnes & Noble <AT&T> 5>3") == "Barnes &amp; Noble &lt;AT&amp;T&gt; 5&gt;3"


def test_strip_html_removes_builder_tags_and_unescapes():
    html = '<b>ACME &amp; Co</b>\n<blockquote expandable>Detail &lt;x&gt;</blockquote>'
    assert strip_html(html) == "ACME & Co\nDetail <x>"


def test_send_message_html_falls_back_to_plain_on_parse_failure(monkeypatch):
    """An entity-parse rejection retries ONCE without parse_mode, tags stripped —
    degraded formatting must never cost the daily delivery."""
    bodies: list[dict] = []

    def fake_urlopen(request, timeout):
        bodies.append(json.loads(request.data.decode("utf-8")))
        if "parse_mode" in bodies[-1]:
            return io.BytesIO(json.dumps({
                "ok": False,
                "description": "Bad Request: can't parse entities: Unsupported start tag",
            }).encode("utf-8"))
        return io.BytesIO(json.dumps({"ok": True, "result": {"message_id": 7}}).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    message_id = send_message("token", CHAT_ID, "<b>Hi</b>", parse_mode="HTML")
    assert message_id == 7
    assert len(bodies) == 2
    assert bodies[0]["parse_mode"] == "HTML"
    assert "parse_mode" not in bodies[1]
    assert bodies[1]["text"] == "Hi"


def test_send_message_html_does_not_mask_other_errors(monkeypatch):
    body = json.dumps({"ok": False, "description": "Bad Request: chat not found"}).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: io.BytesIO(body))
    with pytest.raises(TelegramError, match="chat not found"):
        send_message("token", CHAT_ID, "<b>Hi</b>", parse_mode="HTML")


def test_send_message_without_parse_mode_sends_no_parse_mode(monkeypatch):
    bodies: list[dict] = []

    def fake_urlopen(request, timeout):
        bodies.append(json.loads(request.data.decode("utf-8")))
        return io.BytesIO(json.dumps({"ok": True, "result": {"message_id": 1}}).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    send_message("token", CHAT_ID, "hallo")
    assert "parse_mode" not in bodies[0]


def test_api_raises_telegram_error_on_url_error(monkeypatch):
    """DNS/connection failures (URLError without HTTP status) must surface as TelegramError
    too, so callers' resilience handling covers offline/unreachable states."""

    def unreachable(request, timeout):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    with pytest.raises(TelegramError, match="Name or service not known"):
        send_message("token", CHAT_ID, "hallo")
