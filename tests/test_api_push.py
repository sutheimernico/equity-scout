"""The push endpoints the phone talks to: register, list, unregister, test.

`create_app` mounts the whole cockpit, so these run against the real routing and the real
storage — only the outbound send is stubbed.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from equity_scout.api import create_app
from equity_scout.push_storage import list_subscriptions
from equity_scout.storage import init_db

SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abcdef",
    "keys": {"p256dh": "BPublicKeyBytes", "auth": "AuthSecret"},
    "label": "Android · Chrome",
}


def _client(tmp_path) -> tuple[TestClient, str]:
    db = str(tmp_path / "api.db")
    init_db(db)
    return TestClient(create_app(db)), db


def test_config_exposes_a_usable_application_server_key(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # keep the generated VAPID cache out of the repo
    client, _ = _client(tmp_path)
    body = client.get("/api/push/config").json()
    # base64url, unpadded, 65-byte point -> 87 chars. A shorter key means the browser will
    # reject the subscription with an error nobody can read.
    assert len(body["public_key"]) == 87
    assert body["devices"] == []
    assert body["channels"]["webpush"] is False


def test_subscribe_then_config_lists_the_device(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client, db = _client(tmp_path)
    assert client.post("/api/push/subscribe", json=SUBSCRIPTION).json() == {"ok": True}
    rows = list_subscriptions(db)
    assert len(rows) == 1 and rows[0]["label"] == "Android · Chrome"
    body = client.get("/api/push/config").json()
    assert body["channels"]["webpush"] is True
    # Only the tail of the endpoint is exposed: the full URL is the device's push address
    # and there is no reason for a screen to carry it.
    assert body["devices"][0]["endpoint_hint"] == SUBSCRIPTION["endpoint"][-12:]


def test_subscribe_rejects_an_incomplete_body(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client, db = _client(tmp_path)
    for bad in ({}, {"endpoint": "https://x/y"}, {"endpoint": "notaurl", "keys": {"p256dh": "a", "auth": "b"}}):
        assert client.post("/api/push/subscribe", json=bad).status_code == 422
    assert list_subscriptions(db) == []


def test_unsubscribe_removes_the_device(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client, db = _client(tmp_path)
    client.post("/api/push/subscribe", json=SUBSCRIPTION)
    result = client.post("/api/push/unsubscribe", json={"endpoint": SUBSCRIPTION["endpoint"]})
    assert result.json() == {"ok": True}
    assert list_subscriptions(db) == []


def test_test_endpoint_reports_per_channel_outcome(tmp_path, monkeypatch) -> None:
    """The test button's whole job is to prove the chain end to end, so its answer has to
    name every channel — including the ones that are not configured."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COPILOT_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    client, _ = _client(tmp_path)
    sent: list[dict] = []
    monkeypatch.setattr(
        "equity_scout.push._default_send",
        lambda info, payload, keys, ttl: sent.append(info),
    )
    client.post("/api/push/subscribe", json=SUBSCRIPTION)
    body = client.post("/api/push/test").json()
    assert body["ok"] is True
    assert body["report"]["webpush"]["sent"] == 1
    assert "skipped" in body["report"]["ntfy"]
    assert len(sent) == 1


def test_opportunities_endpoint_returns_the_history(tmp_path, monkeypatch) -> None:
    """Der Verlauf ist der Grund, warum eine Meldung nicht mit dem Wegwischen verschwindet."""
    monkeypatch.chdir(tmp_path)
    from equity_scout.opportunity_storage import record_opportunity

    client, db = _client(tmp_path)
    record_opportunity(
        db,
        {
            "ticker": "MSFT", "name": "Microsoft",
            "headline": "Microsoft steht in seiner Kaufzone",
            "one_liner": "Kurs 100 $", "verdict": "Stark.",
            "why_now": ["Grund eins."], "risk": "Unter 92 $ widerlegt.",
            "plan_line": "Limit 98 $.", "score": 72, "stance": "kaufbereit",
            "price": 100.0, "currency": "USD", "limit": 98.0, "horizon": "lang",
            "explained_by": "regeln", "track_record": None,
        },
        notified_at="2026-08-27T06:00:00+00:00",
        channels={"webpush": {"sent": 1}},
    )
    body = client.get("/api/opportunities").json()
    assert body["counts"] == {"chance": 1, "total": 1}
    row = body["opportunities"][0]
    assert row["why_now"] == ["Grund eins."] and row["buy_limit"] == 98.0


def test_assetlinks_is_readable_without_the_token(tmp_path, monkeypatch) -> None:
    """Chrome holt diese Datei ohne Cookie und ohne Header. Hinter dem Token läuft die
    installierte App dauerhaft mit Adressleiste statt im Vollbild — und niemand sieht,
    warum."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TWA_FINGERPRINT", "AA:BB:CC")
    db = str(tmp_path / "api.db")
    init_db(db)
    client = TestClient(create_app(db, dash_token="geheim"), base_url="http://testserver")
    # Ein Client, der NICHT loopback ist: sonst greift das Gate ohnehin nicht.
    response = client.get(
        "/.well-known/assetlinks.json", headers={"host": "cockpit.example"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body[0]["target"]["sha256_cert_fingerprints"] == ["AA:BB:CC"]


def test_assetlinks_stays_empty_without_a_fingerprint(tmp_path, monkeypatch) -> None:
    """Ein erfundener Fingerabdruck wird von Chrome ohnehin abgelehnt — dann lieber die
    ehrliche leere Liste, an der man sieht, dass der Schritt noch fehlt."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TWA_FINGERPRINT", raising=False)
    client, _ = _client(tmp_path)
    assert client.get("/.well-known/assetlinks.json").json() == []
