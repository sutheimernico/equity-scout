"""Swing lane engine: bullish-event entries, exit rules, holding-period math."""
from __future__ import annotations

from equity_scout.shortterm_book import LaneBook, buy
from equity_scout.st_swing import check_exits, pick_entries


def _event(ticker: str, event_type: str, seen_at: str = "2026-07-20T12:00:00+00:00") -> dict:
    return {"ticker": ticker, "event_type": event_type, "seen_at": seen_at}


def test_pick_entries_takes_only_bullish_events_once_per_ticker() -> None:
    book = LaneBook.fresh("swing")
    events = [
        _event("AAPL", "beat"),
        _event("AAPL", "guidance_up"),  # same ticker — one entry only
        _event("MSFT", "miss"),  # bearish — long-only lane ignores it
        _event("NVDA", "guidance_up"),
    ]
    picks = pick_entries(events, book)
    assert [p["ticker"] for p in picks] == ["AAPL", "NVDA"]
    assert picks[0]["reason"] == "event: beat"


def test_pick_entries_skips_held_tickers_and_respects_slots() -> None:
    book = LaneBook.fresh("swing")
    book, _ = buy(book, "AAPL", 100.0, "t0", fraction=0.1, reason="x")
    events = [_event(t, "beat") for t in ("AAPL", "MSFT", "NVDA", "AMZN")]
    picks = pick_entries(events, book, max_positions=3)
    assert [p["ticker"] for p in picks] == ["MSFT", "NVDA"]  # AAPL held, 2 free slots


def test_check_exits_target_stop_and_max_holding() -> None:
    book = LaneBook.fresh("swing")
    book, _ = buy(book, "WIN", 100.0, "2026-07-18", fraction=0.1, reason="x", slippage_bps=0.0)
    book, _ = buy(book, "LOSE", 100.0, "2026-07-18", fraction=0.1, reason="x", slippage_bps=0.0)
    book, _ = buy(book, "OLD", 100.0, "2026-07-10", fraction=0.1, reason="x", slippage_bps=0.0)
    book, _ = buy(book, "HOLD", 100.0, "2026-07-18", fraction=0.1, reason="x", slippage_bps=0.0)
    prices = {"WIN": 106.0, "LOSE": 96.5, "OLD": 101.0, "HOLD": 101.0}
    exits = {e["ticker"]: e["reason"] for e in check_exits(book, prices, "2026-07-20")}
    assert "Gewinnziel" in exits["WIN"]
    assert "Stop" in exits["LOSE"]
    assert "Max-Haltedauer" in exits["OLD"]
    assert "HOLD" not in exits


def test_check_exits_holds_positions_without_a_price() -> None:
    book = LaneBook.fresh("swing")
    book, _ = buy(book, "GHOST", 100.0, "2026-07-01", fraction=0.1, reason="x")
    assert check_exits(book, {}, "2026-07-20") == []  # old position, but no price -> untouched
