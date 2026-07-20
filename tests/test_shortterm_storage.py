"""Shortterm storage: round trips, idempotency, per-lane isolation."""
from __future__ import annotations

import pytest

from equity_scout.shortterm_book import LaneBook, LanePosition, LaneValuation, TradeFill
from equity_scout.shortterm_storage import (
    append_trades,
    append_valuation,
    get_lane_state,
    load_book,
    load_trades,
    load_valuations,
    save_book,
    set_lane_state,
)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "shortterm.db"


def test_book_round_trip_with_positions_and_benchmark(db) -> None:
    book = LaneBook(
        lane="crypto", initial_capital=10_000.0, cash=7_500.0, benchmark_ticker="BTC",
        benchmark_entry_price=50_000.0,
        positions={"BTC": LanePosition(qty=0.05, entry_price=50_050.0, opened_at="2026-07-20T10:00")},
    )
    save_book(db, book, updated_at="2026-07-20")
    assert load_book(db, "crypto") == book
    assert load_book(db, "swing") is None  # lanes are isolated


def test_valuation_and_trade_inserts_are_idempotent(db) -> None:
    snap = LaneValuation(
        lane="swing", created_at="2026-07-20", equity=10_100.0, total_return=0.01,
        cash=9_000.0, open_positions=1, benchmark_return=0.005,
    )
    append_valuation(db, snap)
    append_valuation(db, snap)
    assert len(load_valuations(db, "swing")) == 1
    fill = TradeFill(
        lane="swing", executed_at="2026-07-20T22:00", ticker="AAPL", side="buy",
        qty=10.0, price=100.05, fees=0.5, reason="event: beat",
    )
    append_trades(db, [fill])
    append_trades(db, [fill])
    trades = load_trades(db, "swing")
    assert len(trades) == 1
    assert trades[0]["realized_pnl"] is None
    assert load_trades(db, "session") == []


def test_lane_state_kv_upserts_per_lane(db) -> None:
    assert get_lane_state(db, "crypto", "last_bar") is None
    set_lane_state(db, "crypto", "last_bar", "2026-07-20T10:15")
    set_lane_state(db, "crypto", "last_bar", "2026-07-20T10:30")
    set_lane_state(db, "session", "last_bar", "other")
    assert get_lane_state(db, "crypto", "last_bar") == "2026-07-20T10:30"
    assert get_lane_state(db, "session", "last_bar") == "other"
