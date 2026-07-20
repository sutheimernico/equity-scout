"""/api/shortterm: seeded lanes with stats and drawdown, honest empty state."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from equity_scout.api import create_app
from equity_scout.shortterm_book import LaneBook, LanePosition, LaneValuation, TradeFill
from equity_scout.shortterm_storage import append_trades, append_valuation, save_book


def _client(tmp_path, shortterm_db: str) -> TestClient:
    return TestClient(create_app(
        db_path=str(tmp_path / "main.db"),
        snapshot=str(tmp_path / "missing.csv"),
        shortterm_db=shortterm_db,
    ))


def test_shortterm_endpoint_reports_lanes_stats_and_drawdown(tmp_path) -> None:
    db = str(tmp_path / "shortterm.db")
    book = LaneBook(
        lane="crypto", initial_capital=10_000.0, cash=7_500.0, benchmark_ticker="BTC",
        benchmark_entry_price=100.0,
        positions={"BTC": LanePosition(qty=0.05, entry_price=105.0, opened_at="t0")},
    )
    save_book(db, book, updated_at="t")
    for created, equity in [("2026-07-19T10:00", 10_000.0), ("2026-07-19T18:00", 10_500.0),
                            ("2026-07-20T10:00", 9_975.0)]:
        append_valuation(db, LaneValuation(
            lane="crypto", created_at=created, equity=equity,
            total_return=equity / 10_000.0 - 1.0, cash=7_500.0, open_positions=1,
            benchmark_return=0.02,
        ))
    append_trades(db, [
        TradeFill(lane="crypto", executed_at="t0", ticker="BTC", side="buy",
                  qty=0.05, price=105.0, fees=0.5, reason="Donchian"),
        TradeFill(lane="crypto", executed_at="t1", ticker="ETH", side="sell",
                  qty=1.0, price=90.0, fees=0.4, reason="Stop", realized_pnl=-10.0),
    ])

    body = _client(tmp_path, db).get("/api/shortterm").json()
    assert body["available"] is True
    lane = body["lanes"][0]
    assert lane["lane"] == "crypto"
    assert lane["equity"] == pytest.approx(9_975.0)
    assert lane["max_drawdown"] == pytest.approx(1 - 9_975.0 / 10_500.0)
    assert lane["benchmark_return"] == pytest.approx(0.02)
    assert lane["stats"]["n_trades"] == 1 and lane["stats"]["win_rate"] == 0.0
    assert lane["open_positions"][0]["ticker"] == "BTC"
    assert len(lane["equity_curve"]) == 3
    assert "disclaimer" in body


def test_shortterm_endpoint_without_lanes_is_unavailable(tmp_path) -> None:
    body = _client(tmp_path, str(tmp_path / "empty.db")).get("/api/shortterm").json()
    assert body["available"] is False and body["lanes"] == []


def test_lanes_carry_promotion_status(tmp_path) -> None:
    from equity_scout.shortterm_book import LaneBook, LaneValuation
    from equity_scout.shortterm_storage import append_valuation, save_book

    shortterm_db = str(tmp_path / "shortterm.db")
    save_book(shortterm_db, LaneBook.fresh("crypto", benchmark_ticker="BTC"), updated_at="t")
    append_valuation(shortterm_db, LaneValuation(
        lane="crypto", created_at="2026-07-20T18:00", equity=10_000.0, total_return=0.0,
        cash=10_000.0, open_positions=0, benchmark_return=None,
    ))
    client = TestClient(create_app(
        db_path=str(tmp_path / "main.db"), snapshot=str(tmp_path / "missing.csv"),
        autotrader_db=str(tmp_path / "autotrader.db"), shortterm_db=shortterm_db,
    ))
    body = client.get("/api/shortterm").json()
    lane = body["lanes"][0]
    assert lane["promoted"] is False
    assert lane["promotion"]["eligible"] is False
    assert "missing" in lane["promotion"]
