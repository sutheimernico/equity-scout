"""Tests for the strategy report service and the /api/strategies endpoint. Offline."""
from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from equity_scout.api import create_app
from equity_scout.data.etf_panel import save_snapshot
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.market import PricePanel
from equity_scout.ml.ledger import init_ledger, record_trial
from equity_scout.ml.meta_model import MetaConfig
from equity_scout.ml.search import EvalResult
from equity_scout.strategy_service import build_reports


def _full_panel(n: int = 320) -> PricePanel:
    # Distinct gentle uptrends per ticker so every strategy has something to decide on.
    data = {}
    for offset, ticker in enumerate(ETF_TICKERS):
        drift = 1.0 + 0.0002 * (offset + 1)
        data[ticker] = [100.0 * drift**i for i in range(n)]
    return PricePanel(pd.DataFrame(data, index=pd.bdate_range("2019-01-01", periods=n)))


def _wavy_panel(n: int = 2600) -> PricePanel:
    # Long, wavy panel so the meta-model actually trains (mirrors tests/test_ml.py's fixture).
    import numpy as np

    idx = pd.bdate_range("2008-01-01", periods=n)
    base = np.array([1.0003**i * (1 + 0.18 * np.sin(i / 70.0)) for i in range(n)])
    data = {
        t: list(100.0 * base * (1 + 0.02 * np.sin(np.arange(n) / 90.0 + off)))
        for off, t in enumerate(["SPY", "VEU", "VWO", "VNQ"])
    }
    data["BIL"] = list(100.0 * 1.00005 ** np.arange(n))
    return PricePanel(pd.DataFrame(data, index=idx))


def test_build_reports_covers_every_strategy():
    from equity_scout.strategies.registry import default_strategies

    reports = build_reports(_full_panel())
    assert len(reports) == len(default_strategies())
    names = {r.name for r in reports}
    assert {"60/40", "Defensive Asset Allocation", "Multi-Strategie-Mix"} <= names
    assert sum(r.is_benchmark for r in reports) == 1  # exactly the 60/40 benchmark


def test_reports_have_curve_metrics_and_sweep():
    report = next(r for r in build_reports(_full_panel()) if r.name == "60/40")
    assert report.equity[0][1] == 1.0  # total-return index starts at 1
    assert len(report.equity) > 5 and len(report.benchmark_equity) == len(report.equity)
    assert len(report.cost_sweep) == 4
    assert report.metrics.deflated_sharpe is not None
    assert report.current_weights  # non-empty target allocation


def test_api_strategies_endpoint(tmp_path):
    snapshot = str(tmp_path / "panel.csv")
    save_snapshot(_full_panel(), snapshot)
    client = TestClient(create_app(snapshot=snapshot))
    resp = client.get("/api/strategies")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["benchmark"] == "60/40"
    assert len(body["strategies"]) == 7  # 6 base strategies + the Multi-Strategie-Mix
    assert "disclaimer" in body


def test_api_strategies_without_snapshot_is_graceful(tmp_path):
    client = TestClient(create_app(snapshot=str(tmp_path / "missing.csv")))
    body = client.get("/api/strategies").json()
    assert body["available"] is False
    assert body["strategies"] == []


def test_api_ml_endpoint(tmp_path):
    # 320-day panel is too short to train → endpoint must still respond gracefully (trained False)
    snapshot = str(tmp_path / "panel.csv")
    save_snapshot(_full_panel(), snapshot)
    body = TestClient(create_app(snapshot=snapshot)).get("/api/ml").json()
    assert body["available"] is True
    assert body["report"]["trained"] is False


def test_api_ml_without_snapshot_is_graceful(tmp_path):
    body = TestClient(create_app(snapshot=str(tmp_path / "missing.csv"))).get("/api/ml").json()
    assert body["available"] is False


def test_api_ml_serves_the_research_loop_champion_config(tmp_path):
    # A champion recorded in the ledger (narrower feature set than the default) must steer the
    # /api/ml report — proving the endpoint follows the search's best finding, not a fixed baseline.
    snapshot = str(tmp_path / "panel.csv")
    save_snapshot(_wavy_panel(), snapshot)

    ledger = str(tmp_path / "research.db")
    init_ledger(ledger)
    champion_config = MetaConfig(features=("vol", "trend"))
    record_trial(
        ledger,
        EvalResult(
            config=champion_config, trained=True, n_bets=50, oos_hit_rate=0.6,
            sharpe_periodic=0.05, n_obs=1000, skew=0.0, kurtosis=3.0,
            cagr=0.08, sharpe=0.9, sortino=1.0, max_drawdown=-0.2, feature_importance={"vol": 1.0},
        ),
        now="2026-06-26T00:00:00",
    )

    body = TestClient(create_app(snapshot=snapshot, ledger=ledger)).get("/api/ml").json()
    assert body["available"] is True
    assert body["report"]["trained"] is True
    assert set(body["report"]["feature_importance"]) <= {"vol", "trend"}
