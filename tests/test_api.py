import equity_scout.entry as entry_mod

from fastapi.testclient import TestClient

from equity_scout.api import create_app
from equity_scout.constants import MODEL_CAVEATS
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
    # Screener-card context rides along per pick (2026-08-07) — honest nulls on a fresh
    # DB with no cached insight/chart/fundamentals, never invented values.
    pick_row = body["buckets"]["balanced"][0]
    assert pick_row["insight"] is None
    assert pick_row["chart"] is None
    assert pick_row["price"] is None
    assert pick_row["analyst_upside_pct"] is None
    assert pick_row["year_high_gap_pct"] is None


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
    # A4: no entry_tb champion registered in this fresh db -> honest gap, not a guess.
    assert body["target_stop"] is None


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
    body = resp.json()
    assert body["available"] is False
    assert body["target_stop"] is None


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


def _register_entry_tb_champion(db: str, barrier_config: dict) -> None:
    """Register + promote a tiny real entry_tb champion carrying `barrier_config` in its metrics
    (A4's real-world layout: `ml.labeling.BarrierConfig.as_dict()` persisted under that key,
    `ml.model_registry.entry_champion`/`register_challenger` read/write path)."""
    import numpy as np
    import pandas as pd

    from equity_scout.ml.entry_features import FEATURE_COLUMNS
    from equity_scout.ml.entry_model import train_entry_model
    from equity_scout.ml.model_registry import promote_if_better, register_challenger

    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(20, len(FEATURE_COLUMNS))), columns=list(FEATURE_COLUMNS))
    y = pd.Series((X[FEATURE_COLUMNS[0]] > 0.0).astype(int).to_numpy())
    version = register_challenger(
        db, train_entry_model(X, y),
        metrics={"auc": 0.7, "n_oos": 200, "barrier_config": barrier_config}, n_train=20,
        now="2026-07-05T12:00:00+00:00", family="entry_tb",
    )
    assert promote_if_better(db, version) is True


def test_entry_endpoint_target_stop_from_entry_tb_champion(tmp_path, monkeypatch):
    import statistics

    db = str(tmp_path / "x.db")
    barrier_config = {"k_pt": 2.0, "k_sl": 1.0, "horizon_days": 40, "vol_window": 5}
    _register_entry_tb_champion(db, barrier_config)

    closes = [100.0, 102.0, 101.0, 105.0, 103.0, 108.0]  # 6 closes -> one vol_window=5 sigma reading
    monkeypatch.setattr(
        entry_mod, "fetch_entry_history",
        lambda t: (closes, [c + 1 for c in closes], [c - 1 for c in closes]),
    )
    client = TestClient(create_app(db))
    resp = client.get("/api/entry/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True

    # Same hand-calculated expectation as test_entry.py's unit test for compute_target_stop.
    returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
    sigma = statistics.stdev(returns)
    price = closes[-1]
    assert body["target_stop"]["target"] == round(price * (1 + 2.0 * sigma), 2)
    assert body["target_stop"]["stop"] == round(price * (1 - 1.0 * sigma), 2)
    assert body["target_stop"]["horizon_days"] == 40


def test_entry_endpoint_target_stop_none_when_champion_lacks_barrier_config(tmp_path, monkeypatch):
    # An entry_tb champion whose metrics predate A3 (no persisted barrier_config) must not crash
    # the endpoint and must not fall back to a guessed default -> honest gap.
    import numpy as np
    import pandas as pd

    from equity_scout.ml.entry_features import FEATURE_COLUMNS
    from equity_scout.ml.entry_model import train_entry_model
    from equity_scout.ml.model_registry import promote_if_better, register_challenger

    db = str(tmp_path / "x.db")
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(20, len(FEATURE_COLUMNS))), columns=list(FEATURE_COLUMNS))
    y = pd.Series((X[FEATURE_COLUMNS[0]] > 0.0).astype(int).to_numpy())
    version = register_challenger(
        db, train_entry_model(X, y), metrics={"auc": 0.7, "n_oos": 200}, n_train=20,
        now="2026-07-05T12:00:00+00:00", family="entry_tb",
    )
    assert promote_if_better(db, version) is True

    closes = [100 + i for i in range(260)]
    monkeypatch.setattr(
        entry_mod, "fetch_entry_history",
        lambda t: (closes, [c + 1 for c in closes], [c - 1 for c in closes]),
    )
    client = TestClient(create_app(db))
    body = client.get("/api/entry/AAPL").json()
    assert body["available"] is True
    assert body["target_stop"] is None


def test_entry_endpoint_target_stop_none_on_short_history_with_champion(tmp_path, monkeypatch):
    # Champion present with the default vol_window=60, but the fetched history (30 closes) is
    # long enough for compute_entry_plan (>= 2) yet too short for a trailing-vol reading -> the
    # plan and the target/stop gap are independent: available True, target_stop None.
    db = str(tmp_path / "x.db")
    _register_entry_tb_champion(db, {"k_pt": 2.0, "k_sl": 1.0, "horizon_days": 40, "vol_window": 60})

    closes = [100.0 + i for i in range(30)]
    monkeypatch.setattr(
        entry_mod, "fetch_entry_history",
        lambda t: (closes, [c + 1 for c in closes], [c - 1 for c in closes]),
    )
    client = TestClient(create_app(db))
    body = client.get("/api/entry/AAPL").json()
    assert body["available"] is True
    assert body["target_stop"] is None


def test_radar_endpoint_returns_latest_watchlist_or_empty(tmp_path, monkeypatch):
    import equity_scout.api as api_mod
    from equity_scout.fundamentals import Fundamentals
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
    # The endpoint calls the CACHED wrapper (fundamentals seam), same as /api/briefs.
    monkeypatch.setattr(
        api_mod, "fetch_fundamentals_cached",
        lambda t: Fundamentals(trailing_pe=None, analyst_target=None, analyst_count=None,
                                currency="USD"),
    )
    loaded = client.get("/api/radar")
    assert loaded.status_code == 200
    body = loaded.json()
    entry = body["watchlist"]["entries"][0]
    assert entry["ticker"] == "DIP"
    # Analyst view rides along per entry; no target -> honest nulls, never a 0.
    assert entry["analyst_upside_pct"] is None
    assert entry["analyst_count"] is None
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
    # C4: rebalance-cadence + survivorship caveats are structural facts about the pipeline,
    # not data-dependent — present even with no model trained yet.
    assert len(empty["caveats"]) == 2
    assert "monatlich" in empty["caveats"][0] and "täglich" in empty["caveats"][0]
    assert "Survivorship-Bias" in empty["caveats"][1]

    # register + promote a tiny real model
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(20, len(FEATURE_COLUMNS))), columns=list(FEATURE_COLUMNS))
    y = pd.Series((X[FEATURE_COLUMNS[0]] > 0.0).astype(int).to_numpy())
    version = register_challenger(
        db, train_entry_model(X, y),
        metrics={"auc": 0.7, "brier": 0.2, "rank_ic": 0.3, "n_oos": 200}, n_train=20,
        now="2026-07-05T12:00:00+00:00",
    )
    assert promote_if_better(db, version) is True  # clears the F2 baseline-quality gate

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
    assert body["caveats"] == empty["caveats"]  # same structural facts regardless of state


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
    # Event-reaction study (Strang B4): present and honest even with nothing queued yet.
    assert body["event_reactions"]["n_resolved"] == 0
    assert body["event_reactions"]["1h"]["measurable"] is False
    assert "disclaimer" in body


def test_model_history_reports_families_and_promotions(tmp_path):
    import numpy as np
    import pandas as pd

    from equity_scout.ml.entry_features import FEATURE_COLUMNS
    from equity_scout.ml.entry_model import train_entry_model
    from equity_scout.ml.model_registry import promote_if_better, register_challenger

    db = str(tmp_path / "x.db")
    rng = np.random.default_rng(1)
    X = pd.DataFrame(rng.normal(size=(40, len(FEATURE_COLUMNS))), columns=list(FEATURE_COLUMNS))
    y = pd.Series((X.iloc[:, 0] > 0).astype(int))
    model = train_entry_model(X, y, model="elastic_net")
    metrics = {"auc": 0.62, "n_oos": 250, "brier": 0.2, "horizon_days": 20, "calibrated": True}
    version = register_challenger(
        db, model, metrics=metrics, n_train=40, now="2026-07-14T00:00:00+00:00"
    )
    promote_if_better(db, version, now="2026-07-14T00:00:00+00:00")

    client = TestClient(create_app(db))
    payload = client.get("/api/model/history").json()
    assert payload["available"] is True
    entry = payload["families"]["entry"]
    assert entry[-1]["is_champion"] is True
    assert entry[-1]["auc"] == 0.62
    assert entry[-1]["horizon_days"] == 20
    assert payload["promotions"][0]["version"] == version
    assert {w["window_days"] for w in payload["resolved_windows"]} == {30, 90}
    assert payload["daily_curve"] == []  # no snapshot persisted yet -> empty, not a crash
    # Learning-curve view carries the same honesty caveats as /api/model (rebalance-cadence
    # mismatch, survivorship bias) — it's exactly the view that suggests "gets better daily".
    assert payload["caveats"] == MODEL_CAVEATS
    assert "disclaimer" in payload

    model_payload = client.get("/api/model").json()
    assert "resolved_windows" in model_payload
    assert model_payload["drift"] is None  # no feature_means/predictions yet -> honest None


def test_model_history_reports_daily_curve_chronologically(tmp_path):
    from equity_scout.ml.learning_curve import save_snapshot

    db = str(tmp_path / "curve.db")
    save_snapshot(
        db, snapshot_date="2026-07-15", created_at="2026-07-15T02:30:00+00:00",
        n_train=120, n_resolved=40, hit_rate=0.55, rank_ic=0.12,
    )
    save_snapshot(
        db, snapshot_date="2026-07-14", created_at="2026-07-14T02:30:00+00:00",
        n_train=None, n_resolved=0, hit_rate=None, rank_ic=None,
    )

    client = TestClient(create_app(db))
    payload = client.get("/api/model/history").json()
    assert [p["snapshot_date"] for p in payload["daily_curve"]] == ["2026-07-14", "2026-07-15"]
    assert payload["daily_curve"][0]["n_train"] is None  # honest gap, not a fabricated 0
    assert payload["daily_curve"][1]["hit_rate"] == 0.55
    # existing fields stay intact alongside the new one (backward compatible)
    assert payload["available"] is False
    assert payload["families"] == {}


def test_signal_stack_returns_honest_nulls_on_empty_db(tmp_path):
    client = TestClient(create_app(str(tmp_path / "x.db")))
    payload = client.get("/api/stack/AAPL").json()
    assert payload["ticker"] == "AAPL"
    assert payload["screener"] is None
    assert payload["radar"] is None
    assert payload["ml"] is None
    assert payload["evidence_events"] == []
    assert payload["person_scores"] == []
    assert client.get("/api/stack/bad ticker!").status_code == 422


def test_radar_joins_latest_ml_score(tmp_path):
    from equity_scout.ml.prediction_ledger import log_predictions
    from equity_scout.radar import Watchlist, WatchlistEntry
    from equity_scout.radar_storage import save_watchlist
    from equity_scout.signals import SignalReading

    db = str(tmp_path / "x.db")
    entry = WatchlistEntry(
        ticker="AAPL", name="Apple", bucket="core", price=100.0,
        entry_zone_low=95.0, entry_zone_high=105.0, proximity=-0.05, in_zone=True,
        composite=0.7, readings=[SignalReading("dip_quality", 0.5, "Grund.")],
        zone_note="Kurs in der Entry-Zone (95.00-105.00).",
        breakdown={"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5},
    )
    save_watchlist(db, Watchlist(created_at="2026-07-14T00:00:00+00:00", entries=[entry]))
    log_predictions(
        db, model_version=3, scored=[("AAPL", 71, {"f": 1.0})],
        now="2026-07-14T00:00:00+00:00", horizon_days=20,
    )
    client = TestClient(create_app(db))
    entries = client.get("/api/radar").json()["watchlist"]["entries"]
    assert entries[0]["ml"] == {
        "score": 71, "created_at": "2026-07-14T00:00:00+00:00", "model_version": 3,
    }


def _scored_run(db) -> int:
    """One saved run + full run_scores rows across regions/sectors for filter tests."""
    from equity_scout.storage import save_run_scores

    inst = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Technology")
    pick = Pick(inst, "balanced", 1, 0.9,
                {"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5})
    run_id = save_run(db, RunResult("2026-07-15T00:00:00", 10, {}, {"balanced": [pick]}))
    full = {
        "balanced": [
            Pick(Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Technology"),
                 "balanced", 1, 0.9, {"value": 0.5}),
            Pick(Instrument("MC.PA", "LVMH", "PA", "EU", "EUR", "Consumer Cyclical"),
                 "balanced", 2, 0.8, {"value": 0.6}),
            Pick(Instrument("7203.T", "Toyota", "TSE", "JP", "JPY", "Automotive"),
                 "balanced", 3, 0.7, {"value": 0.4}),
        ],
        "defensive": [
            Pick(Instrument("SAP.DE", "SAP", "DE", "EU", "EUR", "Technology"),
                 "defensive", 1, 0.85, {"value": 0.7}),
        ],
    }
    save_run_scores(db, run_id, full)
    return run_id


def test_latest_filters_by_region_group_and_sector(tmp_path):
    db = tmp_path / "f.db"
    init_db(db)
    _scored_run(db)
    client = TestClient(create_app(str(db)))

    body = client.get("/api/latest?region=europe").json()
    tickers = [p["instrument"]["ticker"] for picks in body["buckets"].values() for p in picks]
    assert sorted(tickers) == ["MC.PA", "SAP.DE"]
    assert body["filters"] == {"region": "europe", "country": None, "sector": None}
    assert body["filter_matches"] == 2

    body = client.get("/api/latest?sector=technology").json()  # case-insensitive
    tickers = [p["instrument"]["ticker"] for picks in body["buckets"].values() for p in picks]
    assert sorted(tickers) == ["AAPL", "SAP.DE"]


def test_latest_filters_by_country_and_reranks(tmp_path):
    db = tmp_path / "fc.db"
    init_db(db)
    _scored_run(db)
    client = TestClient(create_app(str(db)))
    body = client.get("/api/latest?country=JP").json()
    picks = body["buckets"]["balanced"]
    assert [p["instrument"]["ticker"] for p in picks] == ["7203.T"]
    assert picks[0]["rank"] == 1  # re-ranked within the filtered set (was global rank 3)


def test_latest_filter_no_matches_is_honest(tmp_path):
    db = tmp_path / "fn.db"
    init_db(db)
    _scored_run(db)
    client = TestClient(create_app(str(db)))
    body = client.get("/api/latest?country=XX").json()
    assert body["filter_matches"] == 0
    assert all(picks == [] for picks in body["buckets"].values())


def test_latest_filter_unavailable_for_prefeature_run(tmp_path):
    db = tmp_path / "fu.db"
    init_db(db)
    inst = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Technology")
    pick = Pick(inst, "balanced", 1, 0.9, {"value": 0.5})
    save_run(db, RunResult("2026-07-15T00:00:00", 10, {}, {"balanced": [pick]}))  # no run_scores
    client = TestClient(create_app(str(db)))
    body = client.get("/api/latest?region=europe").json()
    assert body["filter_unavailable"] is True


def test_filters_endpoint_lists_options_with_counts(tmp_path):
    db = tmp_path / "fo.db"
    init_db(db)
    _scored_run(db)
    client = TestClient(create_app(str(db)))
    body = client.get("/api/filters").json()
    assert {"value": "DE", "count": 1} in body["countries"]
    assert {"value": "Technology", "count": 2} in body["sectors"]
    assert set(body["region_groups"]) == {"europe", "americas", "asia", "oceania"}


def test_entry_endpoint_survives_a_network_failure(tmp_path, monkeypatch):
    """R11/P2 (review 2026-07-20): a yfinance timeout is an honest gap, not a 500."""
    def boom(t):
        raise RuntimeError("yfinance timeout")

    monkeypatch.setattr(entry_mod, "fetch_entry_history", boom)
    client = TestClient(create_app(str(tmp_path / "x.db")))
    resp = client.get("/api/entry/AAPL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False and body["reason"] == "fetch_failed"


def test_health_endpoint_is_cheap_and_answers_ok(tmp_path):
    """The phone cockpit polls this every 30 s to tell live data from service-worker
    cache — it must answer without touching the DB or any price feed."""
    db = tmp_path / "health.db"
    init_db(db)
    client = TestClient(create_app(str(db)))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_health_endpoint_is_behind_the_dash_token_gate(tmp_path):
    """An unauthenticated probe must NOT report the cockpit as reachable."""
    db = tmp_path / "health_gated.db"
    init_db(db)
    client = TestClient(create_app(str(db), dash_token="s3cret"))
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", headers={"x-dash-token": "s3cret"}).json()["ok"] is True


def test_evidence_alerts_carry_the_company_name_or_null(tmp_path):
    """A ticker is not information for a beginner (Nico 2026-08-06: "Da steht V — 2
    Kongressmitglieder haben gekauft … Was ist V?").

    The name comes from what the run already knows — the watchlist snapshot and the last
    run's ranking. An alert on a ticker neither of them covers gets `null`, and the UI shows
    the ticker: an invented name would be worse than no name.
    """
    from equity_scout.evidence.storage import record_alert
    from equity_scout.radar import Watchlist, WatchlistEntry
    from equity_scout.radar_storage import save_watchlist
    from equity_scout.signals import SignalReading

    db = tmp_path / "names.db"
    init_db(db)
    now_iso = "2026-08-06T10:00:00+00:00"

    # Name source 1: the watchlist snapshot.
    entry = WatchlistEntry(
        ticker="V", name="Visa Inc.", bucket="core", price=100.0,
        entry_zone_low=95.0, entry_zone_high=105.0, proximity=-0.05, in_zone=True,
        composite=0.7, readings=[SignalReading("dip_quality", 0.5, "Grund.")],
        zone_note="Kurs in der Entry-Zone (95.00-105.00).",
        breakdown={"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5},
    )
    save_watchlist(str(db), Watchlist(created_at=now_iso, entries=[entry]))

    # Name source 2: the persisted ranking of the latest run.
    from equity_scout.storage import save_run_scores

    inst = Instrument("UNH", "UnitedHealth Group Inc.", "NYSE", "US", "USD", "Healthcare")
    pick = Pick(inst, "balanced", 1, 0.7,
                {"value": 0.6, "quality": 0.7, "momentum": 0.5, "growth": 0.5}, thesis="ok")
    run_id = save_run(db, RunResult(now_iso, 10, {}, {"balanced": [pick]}))
    save_run_scores(db, run_id, {"balanced": [pick]})

    for ticker in ("V", "UNH", "ZZZZ"):
        record_alert(str(db), ticker=ticker, reasons=["2 Kongress-Mitglieder haben gekauft"],
                     text="t", telegram_message_id=None, now=now_iso)

    client = TestClient(create_app(str(db)))
    alerts = {a["ticker"]: a for a in client.get("/api/evidence").json()["recent_alerts"]}

    assert alerts["V"]["name"] == "Visa Inc."
    assert alerts["UNH"]["name"] == "UnitedHealth Group Inc."
    assert alerts["ZZZZ"]["name"] is None


def test_chat_advice_question_refuses_without_llm(tmp_path, monkeypatch):
    db = str(tmp_path / "chat.db")
    client = TestClient(create_app(db))

    def boom(*a, **k):  # das LLM DARF bei Ratschlagsfragen nie aufgerufen werden
        raise AssertionError("ask_ollama must not be called for advice questions")

    monkeypatch.setattr("equity_scout.chat.ask_ollama", boom)
    body = client.post("/api/chat", json={"question": "Soll ich Micron kaufen?"}).json()
    assert "keine Anlageberatung" in body["answer"]


def _capture_chat_context(monkeypatch) -> dict:
    captured: dict = {}

    def fake_ask(question, context, **kwargs):
        captured["question"] = question
        captured["context"] = context
        return "Antwort."

    monkeypatch.setattr("equity_scout.chat.ask_ollama", fake_ask)
    return captured


def test_chat_context_carries_dossier_and_glossary_for_a_mentioned_ticker(tmp_path, monkeypatch):
    from equity_scout.radar import build_watchlist
    from equity_scout.radar_storage import save_watchlist
    from tests.test_radar import _finalist
    from tests.test_signals import downtrend_history

    db = str(tmp_path / "chat2.db")
    save_watchlist(db, build_watchlist(
        [_finalist("DIP")], {"DIP": downtrend_history()}, created_at="2026-08-07T09:00:00",
    ))
    client = TestClient(create_app(db))
    captured = _capture_chat_context(monkeypatch)

    client.post("/api/chat", json={"question": "Was weißt du über DIP?"})
    assert "AKTIE" in captured["context"] and "DIP" in captured["context"]
    assert "GLOSSAR" in captured["context"]


def test_chat_context_carries_cached_key_figures(tmp_path, monkeypatch):
    from equity_scout.data.cache import QuoteCache
    from equity_scout.models import Instrument, Pick, RunResult
    from equity_scout.storage import init_db, save_run, save_run_scores

    db = str(tmp_path / "chat3.db")
    cache_db = str(tmp_path / "cache3.db")
    init_db(db)
    run_id = save_run(db, RunResult(created_at="2026-08-07T00:00:00+00:00",
                                    universe_size=1, gated_out={}))
    inst = Instrument("MU", "Micron Technology", "NASDAQ", "US", "USD", "Technology")
    save_run_scores(db, run_id, {"balanced": [Pick(instrument=inst, bucket="balanced",
                                                   rank=1, composite=0.6,
                                                   breakdown={"value": 0.87})]})
    QuoteCache(cache_db).put("MU", {"trailing_pe": 22.3, "price": 160.0}, "2026-08-04")

    client = TestClient(create_app(db, cache_db=cache_db))
    captured = _capture_chat_context(monkeypatch)
    client.post("/api/chat", json={"question": "Wie hoch ist das KGV von Micron?"})

    assert "KGV 22,3" in captured["context"]
    assert "Stand 2026-08-04" in captured["context"]
    assert "Substanz-Bewertung 87/100" in captured["context"]


def test_chat_context_answers_who_bought_with_names(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from equity_scout.evidence.base import EvidenceEvent
    from equity_scout.evidence.storage import record_events

    db = str(tmp_path / "chat4.db")
    today = datetime.now(timezone.utc).date().isoformat()
    record_events(db, [EvidenceEvent(
        source="congress", ticker="INTC", event_key="k1", event_date=today,
        details={"politician": "Thomas H Tuberville", "party": "R", "chamber": "senate",
                 "transaction_date": "2024-05-07", "filing_date": today,
                 "amount_range": "$100,001 - $250,000", "days_to_file": 820},
    )], now=today)

    client = TestClient(create_app(db))
    captured = _capture_chat_context(monkeypatch)
    client.post("/api/chat", json={"question": "Welche Mitglieder haben Intel gekauft?"})

    assert "Tuberville" in captured["context"]
    assert "820 Tage" in captured["context"]


def test_chat_routing_keeps_unrelated_blocks_out_of_the_prompt(tmp_path, monkeypatch):
    db = str(tmp_path / "chat5.db")
    client = TestClient(create_app(db))
    captured = _capture_chat_context(monkeypatch)

    client.post("/api/chat", json={"question": "Wie steht mein Depot?"})
    assert "DEPOTS" in captured["context"]
    # Eine Depotfrage braucht weder die Personen- noch die Ergebnis-Tafel.
    assert "PERSONEN" not in captured["context"]
    assert "ERGEBNISSE" not in captured["context"]


def test_chat_stream_endpoint_streams_text(tmp_path, monkeypatch):
    db = str(tmp_path / "chat6.db")
    client = TestClient(create_app(db))
    monkeypatch.setattr("equity_scout.chat.stream_ollama",
                        lambda q, c, **k: iter(["Hal", "lo"]))
    resp = client.post("/api/chat/stream", json={"question": "Wie ist die Marktlage?"})
    assert resp.status_code == 200
    assert resp.text == "Hallo"


def test_chat_stream_refuses_advice_without_the_llm(tmp_path, monkeypatch):
    db = str(tmp_path / "chat7.db")
    client = TestClient(create_app(db))

    def boom(*a, **k):
        raise AssertionError("stream_ollama must not run for advice questions")

    monkeypatch.setattr("equity_scout.chat.stream_ollama", boom)
    resp = client.post("/api/chat/stream", json={"question": "Soll ich Micron kaufen?"})
    assert "keine Anlageberatung" in resp.text


def test_chat_stream_reports_an_unreachable_model_in_band(tmp_path, monkeypatch):
    from equity_scout.chat import ChatError

    db = str(tmp_path / "chat8.db")
    client = TestClient(create_app(db))

    def failing(q, c, **k):
        raise ChatError("Ollama ist nicht erreichbar.")
        yield  # pragma: no cover - generator marker

    monkeypatch.setattr("equity_scout.chat.stream_ollama", failing)
    resp = client.post("/api/chat/stream", json={"question": "Wie ist die Marktlage?"})
    assert resp.status_code == 200 and "[Fehler:" in resp.text
