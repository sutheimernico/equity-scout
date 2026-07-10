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
    save_run(db, RunResult("2026-06-24T10:00:00", 10, {}, {"balanced": [pick]},
                           data_quality={"attempted": 10, "fetch_error_rate": 0.1}))

    client = TestClient(create_app(str(db)))
    resp = client.get("/api/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["buckets"]["balanced"][0]["instrument"]["ticker"] == "AAPL"
    assert "disclaimer" in body
    # bucket weights are exposed so the dashboard can show score transparency (percentile × weight)
    assert "bucket_weights" in body
    assert set(body["bucket_weights"]) == {"defensive", "balanced", "aggressive"}
    # data-quality report (fetch reliability + completeness) is surfaced for the dashboard
    assert body["data_quality"] == {"attempted": 10, "fetch_error_rate": 0.1}


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


def test_entry_endpoint_caches_within_day(tmp_path, monkeypatch):
    calls = {"n": 0}
    closes = [100 + i for i in range(260)]

    def _fake(_t):
        calls["n"] += 1
        return closes, [c + 1 for c in closes], [c - 1 for c in closes]

    monkeypatch.setattr(entry_mod, "fetch_entry_history", _fake)
    client = TestClient(create_app(str(tmp_path / "x.db")))
    r1 = client.get("/api/entry/AAPL")
    r2 = client.get("/api/entry/AAPL")
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()
    assert calls["n"] == 1  # second request served from cache, fetch not called again


def test_entry_endpoint_accepts_dotted_ticker(tmp_path, monkeypatch):
    closes = [100 + i for i in range(260)]
    monkeypatch.setattr(
        entry_mod,
        "fetch_entry_history",
        lambda _t: (closes, [c + 1 for c in closes], [c - 1 for c in closes]),
    )
    client = TestClient(create_app(str(tmp_path / "x.db")))
    resp = client.get("/api/entry/BRK.B")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["plan"]["ticker"] == "BRK.B"


def test_radar_endpoint_returns_latest_watchlist_or_empty(tmp_path):
    from equity_scout.radar import build_watchlist
    from equity_scout.radar_storage import save_watchlist
    from tests.test_radar import _finalist
    from tests.test_signals import downtrend_history

    db = str(tmp_path / "radar.db")
    client = TestClient(create_app(db))
    empty = client.get("/api/radar")
    assert empty.status_code == 200
    assert empty.json()["watchlist"] is None
    assert "disclaimer" in empty.json()

    save_watchlist(
        db,
        build_watchlist(
            [_finalist("DIP")], {"DIP": downtrend_history()}, created_at="2026-07-04T12:00:00"
        ),
    )
    loaded = client.get("/api/radar")
    assert loaded.status_code == 200
    body = loaded.json()
    assert body["watchlist"]["entries"][0]["ticker"] == "DIP"
    assert "disclaimer" in body


def test_latest_endpoint_migrates_pre_data_quality_db(tmp_path):
    """DBs written before the data_quality column existed must not 500 the read API."""
    import sqlite3

    db = tmp_path / "old-schema.db"
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE runs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, "
            "universe_size INTEGER NOT NULL, gated_out TEXT NOT NULL, "
            "buckets TEXT NOT NULL, gate_stats TEXT NOT NULL DEFAULT '{}')"
        )
        con.execute(
            "INSERT INTO runs (created_at, universe_size, gated_out, buckets) "
            "VALUES ('2026-01-01T00:00:00Z', 1, '[]', '{}')"
        )
    client = TestClient(create_app(str(db)))
    resp = client.get("/api/latest")
    assert resp.status_code == 200


def test_inbox_endpoints_list_and_decide(tmp_path):
    from equity_scout.inbox_storage import create_pitch

    db = str(tmp_path / "inbox.db")
    client = TestClient(create_app(db))

    pitch_id = create_pitch(
        db, ticker="EXE", watchlist_id=1, price=90.0, composite=0.6,
        zone_low=85.0, zone_high=95.0, pitch="P", created_at="2026-07-05T10:00:00+00:00",
    )
    listing = client.get("/api/inbox")
    assert listing.status_code == 200
    assert listing.json()["pitches"][0]["ticker"] == "EXE"
    assert "disclaimer" in listing.json()

    ok = client.post(f"/api/inbox/{pitch_id}/decision", json={"action": "buy"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] is True and "disclaimer" in body
    # the decided row comes back so the dashboard can update in place without a refetch
    assert body["pitch"]["id"] == pitch_id
    assert body["pitch"]["status"] == "buy"
    assert body["pitch"]["decided_at"] is not None
    assert client.get("/api/inbox").json()["pitches"][0]["status"] == "buy"

    conflict = client.post(f"/api/inbox/{pitch_id}/decision", json={"action": "pass"})
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "Pitch unbekannt oder bereits entschieden."
    unknown = client.post("/api/inbox/999/decision", json={"action": "buy"})
    assert unknown.status_code == 409
    # ids beyond SQLite's signed 64-bit range must 409 like any unknown id, never 500
    huge = client.post("/api/inbox/99999999999999999999/decision", json={"action": "buy"})
    assert huge.status_code == 409
    invalid = client.post(f"/api/inbox/{pitch_id}/decision", json={"action": "explode"})
    assert invalid.status_code == 422


def test_arena_endpoint_empty_and_seeded(tmp_path):
    from equity_scout.lane_storage import (
        record_trades,
        save_lane_portfolio,
        save_lane_valuation,
    )
    from equity_scout.lanes import LANE_AUTOPILOT, LANE_NICO, TradeRecord
    from equity_scout.portfolio import Portfolio, Position

    db = str(tmp_path / "arena.db")
    client = TestClient(create_app(db))

    empty = client.get("/api/arena").json()
    assert empty["available"] is False
    assert empty["lanes"] == []
    assert "disclaimer" in empty

    now = "2026-07-05T14:00:00+00:00"
    for lane in (LANE_NICO, LANE_AUTOPILOT):
        pf = Portfolio(
            initial_capital=10_000.0,
            cash=9_499.5,
            positions={
                "EXE": Position(
                    Instrument("EXE", "Expand Energy", "", "", "", ""),
                    shares=5.5, cost_basis=90.77, opened_at=now, last_price=91.0,
                )
            },
            benchmark_shares=16.0,
        )
        save_lane_portfolio(db, lane, pf, updated_at=now)
        save_lane_valuation(db, lane, valued_on="2026-07-04", total_value=10_000.0,
                            total_return=0.0, benchmark_value=10_000.0,
                            benchmark_return=0.0, open_positions=1)
        save_lane_valuation(db, lane, valued_on="2026-07-05", total_value=10_100.0,
                            total_return=0.01, benchmark_value=10_050.0,
                            benchmark_return=0.005, open_positions=1)
        record_trades(db, [TradeRecord(
            created_at=now, lane=lane, ticker="EXE", side="buy", shares=5.5,
            fill_price=90.77, cost=500.5, reason="Grund",
            pitch_id=7 if lane == LANE_NICO else None,
        )])

    body = client.get("/api/arena").json()
    assert body["available"] is True
    assert {lane["lane"] for lane in body["lanes"]} == {LANE_NICO, LANE_AUTOPILOT}
    assert "disclaimer" in body

    nico = next(lane for lane in body["lanes"] if lane["lane"] == LANE_NICO)
    assert nico["initial_capital"] == 10_000.0
    # Latest valuation (2026-07-05) supplies the headline numbers.
    assert nico["total_value"] == 10_100.0
    assert nico["total_return"] == 0.01
    assert nico["benchmark_return"] == 0.005
    assert len(nico["equity_curve"]) == 2
    assert nico["equity_curve"][-1] == ["2026-07-05", 10_100.0, 10_050.0]
    assert nico["open_positions"][0]["ticker"] == "EXE"
    assert nico["open_positions"][0]["last_price"] == 91.0
    assert nico["trades"][0]["ticker"] == "EXE"
    assert nico["trades"][0]["pitch_id"] == 7


def test_model_endpoint_empty_and_after_registration(tmp_path):
    import numpy as np
    import pandas as pd

    from equity_scout.ml.entry_features import FEATURE_COLUMNS
    from equity_scout.ml.entry_model import train_entry_model
    from equity_scout.ml.model_registry import promote_if_better, register_challenger
    from equity_scout.ml.prediction_ledger import (
        due_predictions,
        log_predictions,
        resolve_prediction,
    )

    db = str(tmp_path / "model.db")
    client = TestClient(create_app(db))

    empty = client.get("/api/model").json()
    assert empty["available"] is False
    assert empty["champion"] is None
    assert empty["registry"] == []
    assert empty["resolved"]["n_resolved"] == 0
    assert empty["drift"] is None
    assert "disclaimer" in empty

    # register + promote a tiny real model
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(20, len(FEATURE_COLUMNS))), columns=list(FEATURE_COLUMNS))
    y = pd.Series((X[FEATURE_COLUMNS[0]] > 0.0).astype(int).to_numpy())
    version = register_challenger(
        db, train_entry_model(X, y),
        metrics={"auc": 0.7, "brier": 0.2, "rank_ic": 0.3}, n_train=20,
        now="2026-07-05T12:00:00+00:00",
    )
    promote_if_better(db, version)

    # log + resolve a couple predictions against realized outcomes
    log_predictions(
        db, model_version=version, horizon_days=20, now="2026-01-01T00:00:00+00:00",
        scored=[("AAA", 80, {"mkt_vol": 0.1}), ("BBB", 30, {"mkt_vol": 0.1})],
    )
    for d in due_predictions(db, "2026-03-01T00:00:00+00:00"):
        resolve_prediction(
            db, d["id"], realized_relative_return=0.02, resolved_at="2026-03-01T00:00:00+00:00"
        )

    body = client.get("/api/model").json()
    assert body["available"] is True
    assert body["champion"]["version"] == version
    assert body["champion"]["model_kind"] == "random_forest"
    assert body["champion"]["metrics"]["auc"] == 0.7
    assert "created_at" in body["champion"]
    assert len(body["registry"]) == 1
    assert body["resolved"]["n_resolved"] == 2
    assert "disclaimer" in body


def test_evidence_endpoint_returns_events_alerts_and_stats(tmp_path):
    from datetime import datetime, timezone

    from equity_scout.evidence.base import SOURCE_CONGRESS, EvidenceEvent
    from equity_scout.evidence.ledger import log_evidence
    from equity_scout.evidence.storage import record_alert, record_events

    db = tmp_path / "api.db"
    init_db(db)
    # The endpoint reads the real clock, so seed events dated today (test setup only).
    today = datetime.now(timezone.utc).date().isoformat()
    now_iso = f"{today}T00:00:00+00:00"
    events = [
        EvidenceEvent(
            source=SOURCE_CONGRESS, ticker="EXE", event_key="k1", event_date=today,
            details={"politician": "Jane Doe", "filing_date": today},
        )
    ]
    record_events(str(db), events, now=now_iso)
    log_evidence(str(db), events, now=now_iso)
    record_alert(str(db), ticker="EXE", reasons=["r"], text="t",
                 telegram_message_id=None, now=now_iso)

    client = TestClient(create_app(str(db)))
    body = client.get("/api/evidence").json()

    assert body["events_by_ticker"]["EXE"][0]["details"]["politician"] == "Jane Doe"
    assert body["recent_alerts"][0]["ticker"] == "EXE"
    assert body["stats_by_source"]["congress"]["n_open"] == 1
    assert body["stats_by_source"]["congress"]["n_resolved"] == 0
    assert body["person_scores"] == []  # present even when nothing is measured yet
    assert "disclaimer" in body
