"""/api/autodepot: seeded shape and honest empty state."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from equity_scout.api import create_app
from equity_scout.autotrader_engine import AutoDepotAccount, AutoDepotValuation, TradeRecord
from equity_scout.autotrader_protections import BreakerState, RiskEvent
from equity_scout.autotrader_storage import record_advance, save_depot


def _client(tmp_path, autotrader_db: str) -> TestClient:
    return TestClient(create_app(
        db_path=str(tmp_path / "main.db"),
        snapshot=str(tmp_path / "missing.csv"),
        autotrader_db=autotrader_db,
    ))


def test_autodepot_endpoint_returns_seeded_depot(tmp_path) -> None:
    db = str(tmp_path / "autotrader.db")
    save_depot(db, AutoDepotAccount(
        initial_capital=100_000.0, equity=101_500.0, benchmark_ticker="SPY",
        benchmark_equity=101_100.0, peak_equity=102_000.0, last_as_of="2026-07-17",
        weights={"XLK": 0.1, "IEF": 0.05},
        breaker=BreakerState(stage=0, changed_at=None),
        sleeve_weights={"gem": 0.6, "daa": 0.4}, sleeve_mode="tilt",
    ), updated_at="2026-07-17")
    record_advance(db, AutoDepotValuation(
        created_at="2026-07-17", equity=101_500.0, total_return=0.015,
        benchmark_equity=101_100.0, benchmark_return=0.011,
        gross_exposure=0.15, drawdown=0.005, equity_eur=91_350.0, fx_rate=0.9,
        trades=(TradeRecord("2026-07-17", "XLK", 0.02, 2_030.0, 2.03),),
        risk_events=(RiskEvent("vol_target", "scale_0.9", "Vol über Ziel"),),
    ))

    body = _client(tmp_path, db).get("/api/autodepot").json()
    assert body["available"] is True
    assert body["account"]["equity"] == pytest.approx(101_500.0)
    assert body["account"]["total_return"] == pytest.approx(0.015)
    assert body["account"]["weights"] == {"XLK": 0.1, "IEF": 0.05}
    assert body["account"]["sleeve_mode"] == "tilt"
    assert body["latest"]["gross_exposure"] == pytest.approx(0.15)
    assert body["latest"]["equity_eur"] == pytest.approx(91_350.0)
    assert body["equity_curve"] == [["2026-07-17", 101_500.0, 101_100.0]]
    assert [t["ticker"] for t in body["trades"]] == ["XLK"]
    assert body["risk_events"][0]["protection"] == "vol_target"
    assert "disclaimer" in body


def test_autodepot_endpoint_without_depot_is_unavailable(tmp_path) -> None:
    body = _client(tmp_path, str(tmp_path / "empty.db")).get("/api/autodepot").json()
    assert body == {"available": False, "disclaimer": body["disclaimer"]}
