import equity_scout.entry as entry_mod

from fastapi.testclient import TestClient

from equity_scout.api import create_app
from equity_scout.models import Instrument, Pick, RunResult
from equity_scout.storage import init_db, save_run


def test_latest_endpoint_returns_buckets(tmp_path):
    db = tmp_path / "api.db"
    init_db(db)
    inst = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Tech")
    pick = Pick(inst, "balanced", 1, 0.7,
                {"value": 0.6, "quality": 0.7, "momentum": 0.5, "growth": 0.5}, thesis="ok")
    save_run(db, RunResult("2026-06-24T10:00:00", 10, {}, {"balanced": [pick]}))

    client = TestClient(create_app(str(db)))
    resp = client.get("/api/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["buckets"]["balanced"][0]["instrument"]["ticker"] == "AAPL"
    assert "disclaimer" in body
    # bucket weights are exposed so the dashboard can show score transparency (percentile × weight)
    assert "bucket_weights" in body
    assert set(body["bucket_weights"]) == {"defensive", "balanced", "aggressive"}


def test_latest_endpoint_empty_db_still_has_disclaimer(tmp_path):
    db = tmp_path / "empty.db"
    init_db(db)
    client = TestClient(create_app(str(db)))
    body = client.get("/api/latest").json()
    assert body["buckets"] == {}
    assert body["disclaimer"]


def test_portfolio_endpoint_handles_no_portfolio(tmp_path):
    db = tmp_path / "np.db"
    init_db(db)  # funnel tables only, no portfolio yet
    client = TestClient(create_app(str(db)))
    body = client.get("/api/portfolio").json()
    assert body["exists"] is False
    assert body["positions"] == []


def test_history_endpoint_returns_runs(tmp_path):
    db = tmp_path / "h.db"
    init_db(db)
    inst = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Tech")
    pick = Pick(inst, "balanced", 1, 0.7,
                {"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5})
    save_run(db, RunResult("2026-06-24T10:00:00", 10, {}, {"balanced": [pick]}))
    client = TestClient(create_app(str(db)))
    body = client.get("/api/history").json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["picks"]["balanced"] == ["AAPL"]


def test_entry_endpoint_returns_plan(tmp_path, monkeypatch):
    closes = [100 + i for i in range(260)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    monkeypatch.setattr(entry_mod, "fetch_entry_history", lambda t: (closes, highs, lows))

    client = TestClient(create_app(str(tmp_path / "x.db")))
    resp = client.get("/api/entry/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["plan"]["ticker"] == "AAPL"
    assert "disclaimer" in body
    assert len(body["plan"]["dca_tranches"]) == 4


def test_entry_endpoint_rejects_bad_ticker(tmp_path):
    client = TestClient(create_app(str(tmp_path / "x.db")))
    resp = client.get("/api/entry/..%2Fetc")  # path-traversal-ish junk
    # FastAPI may 404 the malformed path, or our validator 400s a decoded bad ticker.
    assert resp.status_code in (400, 404)


def test_entry_endpoint_unavailable_on_short_history(tmp_path, monkeypatch):
    monkeypatch.setattr(entry_mod, "fetch_entry_history", lambda t: ([], [], []))
    client = TestClient(create_app(str(tmp_path / "x.db")))
    resp = client.get("/api/entry/ZZZZ")
    assert resp.status_code == 200
    assert resp.json()["available"] is False
