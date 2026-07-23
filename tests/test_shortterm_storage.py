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
    persist_lane_step,
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


def _fill(lane: str = "swing") -> TradeFill:
    return TradeFill(lane=lane, executed_at="2026-07-20T14:00", ticker="AAPL", side="buy",
                     qty=5.0, price=100.0, fees=0.25, reason="event: beat")


def test_load_trades_limit_none_returns_all_rows(db) -> None:
    """v13 R6: the promotion gate's all-time aggregates read with limit=None — every
    finite cap (the default 200 included) would silently understate them one day."""
    fills = [
        TradeFill(lane="swing", executed_at=f"2026-07-20T14:{i // 60:02d}:{i % 60:02d}",
                  ticker="AAPL", side="buy", qty=1.0, price=100.0, fees=0.1,
                  reason="event: beat")
        for i in range(250)
    ]
    append_trades(db, fills)
    assert len(load_trades(db, "swing")) == 200  # default cap unchanged
    assert len(load_trades(db, "swing", limit=None)) == 250


def test_persist_lane_step_commits_everything_together(db) -> None:
    book = LaneBook.fresh("swing")
    snap = LaneValuation(lane="swing", created_at="2026-07-20", equity=10_000.0,
                         total_return=0.0, cash=9_500.0, open_positions=1,
                         benchmark_return=None)
    persist_lane_step(db, book, updated_at="2026-07-20", trades=[_fill()],
                      valuation=snap, state=[("events_seen_until", "2026-07-20T14:00")])
    assert load_book(db, "swing") == book
    assert len(load_trades(db, "swing")) == 1
    assert len(load_valuations(db, "swing")) == 1
    assert get_lane_state(db, "swing", "events_seen_until") == "2026-07-20T14:00"

    # idempotent re-run: natural keys ignore duplicates
    persist_lane_step(db, book, updated_at="2026-07-20", trades=[_fill()], valuation=snap)
    assert len(load_trades(db, "swing")) == 1
    assert len(load_valuations(db, "swing")) == 1


class _ExplodingFill:
    """Stands in for a TradeFill; blows up mid-write to simulate an interrupt."""

    lane = "swing"
    executed_at = "2026-07-20T14:00"
    ticker = "AAPL"
    side = "buy"
    qty = 5.0
    price = 100.0
    fees = 0.25
    reason = "event: beat"

    @property
    def realized_pnl(self) -> float:
        raise RuntimeError("boom mid-persist")


def test_persist_lane_step_rolls_back_completely_on_mid_write_failure(db) -> None:
    """R4/P1 (review 2026-07-20): an interrupt mid-persist must not divorce the book from
    its trade log / markers — a fill either exists everywhere or nowhere."""
    book = LaneBook.fresh("swing")
    snap = LaneValuation(lane="swing", created_at="2026-07-20", equity=10_000.0,
                         total_return=0.0, cash=9_500.0, open_positions=1,
                         benchmark_return=None)
    with pytest.raises(RuntimeError):
        persist_lane_step(db, book, updated_at="2026-07-20", trades=[_ExplodingFill()],
                          valuation=snap, state=[("events_seen_until", "X")])
    assert load_book(db, "swing") is None
    assert load_trades(db, "swing") == []
    assert load_valuations(db, "swing") == []
    assert get_lane_state(db, "swing", "events_seen_until") is None
