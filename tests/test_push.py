"""Web Push: key handling, subscription lifecycle, and the fan-out over three channels.

Everything network-facing goes through an injected `send`, so nothing here touches a push
service, ntfy, or Telegram — the LOOP.md determinism rule.
"""
from __future__ import annotations

import json

import pytest

from equity_scout import channels, ntfy, push
from equity_scout.push_storage import (
    delete_subscription,
    list_subscriptions,
    record_failure,
    save_subscription,
)


def _sub(db: str, endpoint: str = "https://fcm.example/abc") -> None:
    save_subscription(
        db,
        endpoint=endpoint,
        p256dh="key",
        auth="auth",
        label="Android · Chrome",
        created_at="2026-08-27T10:00:00+00:00",
    )


def test_generated_public_key_is_a_65_byte_point(tmp_path) -> None:
    """`applicationServerKey` must decode to an uncompressed P-256 point — 0x04 + 32 + 32.
    Anything else fails inside the browser with an opaque error."""
    import base64

    keys = push.generate_keys()
    padded = keys.public_key + "=" * (-len(keys.public_key) % 4)
    raw = base64.urlsafe_b64decode(padded)
    assert len(raw) == 65 and raw[0] == 0x04
    assert "BEGIN PRIVATE KEY" in keys.private_pem


def test_keys_survive_a_restart(tmp_path, monkeypatch) -> None:
    """The cache file is the whole point: a new key silently invalidates every phone's
    subscription, and nothing would report that."""
    monkeypatch.delenv("VAPID_PRIVATE_KEY_PEM", raising=False)
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    path = str(tmp_path / "vapid.json")
    first = push.load_or_create_keys(path)
    second = push.load_or_create_keys(path)
    assert first.public_key == second.public_key


def test_env_overrides_the_cache_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VAPID_PRIVATE_KEY_PEM", "pem")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
    keys = push.load_or_create_keys(str(tmp_path / "vapid.json"))
    assert (keys.private_pem, keys.public_key) == ("pem", "pub")


def test_subscription_upsert_is_idempotent_and_clears_failures(tmp_path) -> None:
    db = str(tmp_path / "main.db")
    _sub(db)
    record_failure(db, "https://fcm.example/abc", error="boom")
    assert list_subscriptions(db)[0]["failures"] == 1
    _sub(db)  # same endpoint, re-subscribed
    rows = list_subscriptions(db)
    assert len(rows) == 1 and rows[0]["failures"] == 0 and rows[0]["last_error"] is None


def test_delete_reports_whether_anything_was_removed(tmp_path) -> None:
    db = str(tmp_path / "main.db")
    _sub(db)
    assert delete_subscription(db, "https://fcm.example/abc") is True
    assert delete_subscription(db, "https://fcm.example/abc") is False


def test_broadcast_records_success_per_device(tmp_path) -> None:
    db = str(tmp_path / "main.db")
    _sub(db, "https://fcm.example/one")
    _sub(db, "https://fcm.example/two")
    seen: list[str] = []

    def send(info, payload, keys, ttl):  # noqa: ANN001
        seen.append(info["endpoint"])

    report = push.broadcast("{}", db_path=db, send=send, keys=push.VapidKeys("pem", "pub"))
    assert report["sent"] == 2 and report["failed"] == 0
    assert sorted(seen) == ["https://fcm.example/one", "https://fcm.example/two"]
    assert all(row["last_ok_at"] is not None for row in list_subscriptions(db))


def test_gone_subscription_is_deleted_not_retried_forever(tmp_path) -> None:
    """410 = the browser revoked it. Keeping the row would make the device count lie about
    how many phones can actually be reached."""
    db = str(tmp_path / "main.db")
    _sub(db)

    def send(info, payload, keys, ttl):  # noqa: ANN001
        raise push.PushError("gone", status=410)

    report = push.broadcast("{}", db_path=db, send=send, keys=push.VapidKeys("pem", "pub"))
    assert report["removed"] == 1 and list_subscriptions(db) == []


def test_transient_failure_keeps_the_device_and_counts_it(tmp_path) -> None:
    db = str(tmp_path / "main.db")
    _sub(db)

    def send(info, payload, keys, ttl):  # noqa: ANN001
        raise push.PushError("service unavailable", status=503)

    report = push.broadcast("{}", db_path=db, send=send, keys=push.VapidKeys("pem", "pub"))
    assert report["failed"] == 1 and len(list_subscriptions(db)) == 1
    assert list_subscriptions(db)[0]["failures"] == 1


def test_one_dead_device_does_not_stop_the_others(tmp_path) -> None:
    db = str(tmp_path / "main.db")
    _sub(db, "https://fcm.example/dead")
    _sub(db, "https://fcm.example/alive")

    def send(info, payload, keys, ttl):  # noqa: ANN001
        if info["endpoint"].endswith("dead"):
            raise RuntimeError("transport exploded")

    report = push.broadcast("{}", db_path=db, send=send, keys=push.VapidKeys("pem", "pub"))
    assert report["sent"] == 1 and report["failed"] == 1


def test_payload_carries_tag_only_when_given() -> None:
    with_tag = json.loads(push.build_payload(title="t", body="b", tag="MU"))
    without = json.loads(push.build_payload(title="t", body="b"))
    assert with_tag["tag"] == "MU" and "tag" not in without


def test_public_url_is_absolute_when_the_origin_is_known(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://host.ts.net/")
    assert channels.public_url("/?view=heute") == "https://host.ts.net/?view=heute"
    monkeypatch.delenv("PUBLIC_BASE_URL")
    assert channels.public_url("/?view=heute") == "/?view=heute"


def test_deliver_is_independent_per_channel(tmp_path) -> None:
    """A dead Telegram token must not cost the phone push — that is the whole reason this
    fan-out exists instead of a chain of ifs at each call site."""
    db = str(tmp_path / "main.db")
    _sub(db)
    pushed: list[str] = []

    def failing_telegram(token, chat_id, text):  # noqa: ANN001
        raise RuntimeError("telegram down")

    def ok_push(**kwargs):  # noqa: ANN003
        pushed.append(kwargs["title"])
        return {"sent": 1}

    report = channels.deliver(
        channels.Alert(title="T", body="B", telegram_html="<b>T</b>"),
        db_path=db,
        env={"COPILOT_TG_BOT_TOKEN": "t", "COPILOT_TG_CHAT_ID": "1"},
        send_telegram=failing_telegram,
        send_push=ok_push,
    )
    assert "error" in report["telegram"]
    assert report["webpush"] == {"sent": 1} and pushed == ["T"]
    assert report["ntfy"] == {"skipped": "kein NTFY_TOPIC gesetzt"}


def test_deliver_skips_telegram_when_no_long_form_was_supplied(tmp_path) -> None:
    report = channels.deliver(
        channels.Alert(title="T", body="B"),
        db_path=str(tmp_path / "main.db"),
        env={"COPILOT_TG_BOT_TOKEN": "t", "COPILOT_TG_CHAT_ID": "1"},
        send_push=lambda **kwargs: {"sent": 0},
    )
    assert "telegram" not in report


def test_ntfy_config_needs_a_topic() -> None:
    assert ntfy.load_config({}) is None
    assert ntfy.load_config({"NTFY_TOPIC": "  "}) is None
    assert ntfy.load_config({"NTFY_TOPIC": "abc"}) == {
        "topic": "abc",
        "server": "https://ntfy.sh",
    }


def test_ntfy_send_posts_json_with_a_click_through(tmp_path) -> None:
    captured: dict = {}

    class _Response:
        status = 200

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *args):  # noqa: ANN002, ANN204
            return False

    def opener(request, timeout=None):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    ntfy.send(
        topic="secret-topic",
        title="Titel",
        body="Text",
        url="https://host.ts.net/?view=heute",
        opener=opener,
    )
    assert captured["body"]["topic"] == "secret-topic"
    assert captured["body"]["click"] == "https://host.ts.net/?view=heute"
    assert captured["body"]["actions"][0]["url"] == "https://host.ts.net/?view=heute"


def test_ntfy_raises_on_http_error() -> None:
    import urllib.error

    def opener(request, timeout=None):  # noqa: ANN001
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    with pytest.raises(ntfy.NtfyError, match="429"):
        ntfy.send(topic="t", title="a", body="b", opener=opener)
