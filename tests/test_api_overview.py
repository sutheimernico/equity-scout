"""/api/overview (v12 I1): one payload across all horizons — total wealth, per-book
day P&L, and short/mid/long subtotals. Honest omission when nothing exists yet."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from equity_scout.api import create_app
from equity_scout.autotrader_engine import AutoDepotAccount, AutoDepotValuation
from equity_scout.autotrader_storage import record_advance, save_depot
from equity_scout.shortterm_book import LaneBook, LaneValuation
from equity_scout.shortterm_storage import append_valuation, save_book


def _client(tmp_path, autotrader_db: str, shortterm_db: str) -> TestClient:
    return TestClient(create_app(
        db_path=str(tmp_path / "main.db"),
        snapshot=str(tmp_path / "missing.csv"),
        autotrader_db=autotrader_db,
        shortterm_db=shortterm_db,
    ))


def _valuation(day: str, equity: float) -> AutoDepotValuation:
    return AutoDepotValuation(
        created_at=day, equity=equity, total_return=equity / 100_000.0 - 1.0,
        benchmark_equity=100_000.0, benchmark_return=0.0,
        gross_exposure=0.8, drawdown=0.0,
    )


def test_overview_aggregates_books_horizons_and_total(tmp_path) -> None:
    autotrader_db = str(tmp_path / "autotrader.db")
    shortterm_db = str(tmp_path / "shortterm.db")
    account = AutoDepotAccount(
        initial_capital=100_000.0, equity=102_000.0, benchmark_ticker="SPY",
        benchmark_equity=100_000.0, peak_equity=102_000.0, last_as_of="2026-07-20",
        weights={}, sleeve_weights={"gem": 0.6, "ML Long Bot": 0.4}, sleeve_mode="tilt",
    )
    save_depot(autotrader_db, account, updated_at="2026-07-20")
    record_advance(autotrader_db, _valuation("2026-07-17", 101_000.0))
    record_advance(autotrader_db, _valuation("2026-07-20", 102_000.0))

    save_book(shortterm_db, LaneBook.fresh("crypto", benchmark_ticker="BTC"), updated_at="t")
    append_valuation(shortterm_db, LaneValuation(
        lane="crypto", created_at="2000-01-01T00:00", equity=10_000.0, total_return=0.0,
        cash=10_000.0, open_positions=0, benchmark_return=None,
    ))
    append_valuation(shortterm_db, LaneValuation(
        lane="crypto", created_at=f"{date.today().isoformat()}T02:00", equity=10_100.0,
        total_return=0.01, cash=7_000.0, open_positions=1, benchmark_return=0.02,
    ))

    body = _client(tmp_path, autotrader_db, shortterm_db).get("/api/overview").json()
    assert body["available"] is True
    keys = {b["key"]: b for b in body["books"]}
    assert keys["autodepot"]["day_pnl"] == pytest.approx(1_000.0)
    assert keys["autodepot"]["equity"] == pytest.approx(102_000.0)
    assert keys["arena_crypto"]["day_pnl"] == pytest.approx(100.0)
    assert keys["arena_crypto"]["horizon"] == "short"

    assert body["horizons"]["short"]["equity"] == pytest.approx(10_100.0)
    assert body["horizons"]["mid"]["equity"] == pytest.approx(102_000.0 * 0.4)
    assert body["horizons"]["long"]["equity"] == pytest.approx(102_000.0 * 0.6)
    assert "Sleeve-Gewichten" in body["horizons"]["mid"]["note"]

    assert body["total"]["equity"] == pytest.approx(112_100.0)
    assert body["total"]["day_pnl"] == pytest.approx(1_100.0)
    assert "disclaimer" in body


def test_overview_is_honest_on_empty_dbs(tmp_path) -> None:
    body = _client(
        tmp_path, str(tmp_path / "a.db"), str(tmp_path / "s.db")
    ).get("/api/overview").json()
    assert body["available"] is False
