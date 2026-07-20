"""Dashboard token gate (v12 M1): nothing goes LAN without auth — localhost stays free,
everything else needs the shared secret (query once -> cookie, or header)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from equity_scout.api import create_app


def _app(tmp_path, token: str | None):
    return create_app(
        db_path=str(tmp_path / "main.db"),
        snapshot=str(tmp_path / "missing.csv"),
        dash_token=token,
    )


def test_without_configured_token_everything_stays_open(tmp_path) -> None:
    client = TestClient(_app(tmp_path, None))
    assert client.get("/api/latest").status_code == 200


def test_remote_request_without_token_is_rejected(tmp_path) -> None:
    client = TestClient(_app(tmp_path, "geheim"))  # testclient host != loopback
    assert client.get("/api/latest").status_code == 401


def test_query_token_works_once_and_sets_the_cookie(tmp_path) -> None:
    client = TestClient(_app(tmp_path, "geheim"))
    resp = client.get("/api/latest?token=geheim")
    assert resp.status_code == 200
    assert resp.cookies.get("es_dash") == "geheim"
    # the client keeps the cookie -> next request needs no token in the URL
    assert client.get("/api/latest").status_code == 200


def test_header_token_and_wrong_token(tmp_path) -> None:
    client = TestClient(_app(tmp_path, "geheim"))
    assert client.get("/api/latest", headers={"X-Dash-Token": "geheim"}).status_code == 200
    assert client.get("/api/latest?token=falsch").status_code == 401


def test_localhost_is_exempt(tmp_path) -> None:
    client = TestClient(_app(tmp_path, "geheim"), client=("127.0.0.1", 9999))
    assert client.get("/api/latest").status_code == 200
