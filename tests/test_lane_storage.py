"""Lane persistence: portfolio round-trip, day-idempotent valuations, append-only trades."""
from __future__ import annotations

import sqlite3

from equity_scout.lane_storage import (
    executed_pitch_ids,
    init_lane_db,
    load_lane_portfolio,
    load_lane_trades,
    load_lane_valuations,
    record_trades,
    save_lane_portfolio,
    save_lane_valuation,
)
from equity_scout.lanes import LANE_NICO, TradeRecord
from equity_scout.models import Instrument
from equity_scout.portfolio import Portfolio, Position

NOW = "2026-07-05T14:00:00+00:00"


def _trade(ticker: str = "EXE", pitch_id: int | None = 7) -> TradeRecord:
    return TradeRecord(
        created_at=NOW, lane=LANE_NICO, ticker=ticker, side="buy", shares=5.5,
        fill_price=90.77, cost=500.5, reason="Grund", pitch_id=pitch_id,
    )


def test_lane_portfolio_round_trip_reconstructs_dataclasses(tmp_path):
    db = str(tmp_path / "lanes.db")
    portfolio = Portfolio(
        initial_capital=10_000.0,
        cash=9_499.5,
        positions={
            "EXE": Position(
                Instrument("EXE", "Expand Energy", "", "", "", ""),
                shares=5.5, cost_basis=90.77, opened_at=NOW, last_price=91.0,
            )
        },
        benchmark_shares=16.0,
    )
    save_lane_portfolio(db, LANE_NICO, portfolio, updated_at=NOW)
    loaded = load_lane_portfolio(db, LANE_NICO)
    assert loaded == portfolio  # full dataclass equality incl. nested Position/Instrument


def test_load_lane_portfolio_none_when_missing(tmp_path):
    db = str(tmp_path / "lanes.db")
    init_lane_db(db)
    assert load_lane_portfolio(db, LANE_NICO) is None


def test_lane_valuation_idempotent_per_day(tmp_path):
    db = str(tmp_path / "lanes.db")
    save_lane_valuation(
        db, LANE_NICO, valued_on="2026-07-05", total_value=10_100.0, total_return=0.01,
        benchmark_value=10_050.0, benchmark_return=0.005, open_positions=1,
    )
    save_lane_valuation(  # same day again — later run wins, no second row
        db, LANE_NICO, valued_on="2026-07-05", total_value=10_200.0, total_return=0.02,
        benchmark_value=10_050.0, benchmark_return=0.005, open_positions=1,
    )
    rows = load_lane_valuations(db, LANE_NICO)
    assert len(rows) == 1
    assert rows[0]["total_value"] == 10_200.0


def test_trades_append_only_and_executed_pitch_ids(tmp_path):
    db = str(tmp_path / "lanes.db")
    record_trades(db, [_trade(pitch_id=7), _trade(ticker="ABC", pitch_id=None)])
    record_trades(db, [_trade(ticker="DEF", pitch_id=9)])
    trades = load_lane_trades(db, LANE_NICO)
    assert [t["ticker"] for t in trades] == ["DEF", "ABC", "EXE"]  # newest first
    assert executed_pitch_ids(db, LANE_NICO) == {7, 9}
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM lane_trades").fetchone()[0] == 3
