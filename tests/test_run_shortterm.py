"""Runner lanes end-to-end with faked feeds: fills persisted, markers, idempotency."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

import scripts.run_shortterm as runner
from equity_scout.market import PricePanel
from equity_scout.shortterm_storage import (
    get_lane_state,
    load_book,
    load_trades,
    load_valuations,
)

NOW = datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "shortterm.db")


def _crypto_bars(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-07-20 00:00", periods=len(closes), freq="15min", tz="UTC")
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
         "close": closes},
        index=index,
    )


def test_crypto_lane_books_a_breakout_and_is_idempotent(db) -> None:
    # completed_bars drops the running last row -> the judged signal bar is the 105 close
    bars = _crypto_bars([100.0] * 21 + [105.0, 106.0])

    def fake_fetch(pair):  # noqa: ANN001, ANN202
        return bars if pair == "XBTUSD" else None

    runner.run_crypto(db, now=NOW, fetch=fake_fetch)
    book = load_book(db, "crypto")
    assert book is not None and "BTC" in book.positions
    trades = load_trades(db, "crypto")
    assert len(trades) == 1 and trades[0]["side"] == "buy"
    assert book.benchmark_entry_price == pytest.approx(105.0)
    assert len(load_valuations(db, "crypto")) == 1
    assert get_lane_state(db, "crypto", "last_bar_BTC") is not None

    runner.run_crypto(db, now=NOW, fetch=fake_fetch)  # same bars again -> no new trade
    assert len(load_trades(db, "crypto")) == 1


def test_crypto_lane_skips_honestly_when_feed_is_down(db) -> None:
    runner.run_crypto(db, now=NOW, fetch=lambda pair: None)
    assert load_book(db, "crypto") is None
    assert load_valuations(db, "crypto") == []


def test_swing_lane_buys_fresh_bullish_events(db, tmp_path, monkeypatch) -> None:
    events = [
        {"ticker": "AAPL", "event_type": "beat", "seen_at": "2026-07-20T14:00:00+00:00"},
        {"ticker": "MSFT", "event_type": "miss", "seen_at": "2026-07-20T14:00:00+00:00"},
    ]
    monkeypatch.setattr(runner, "load_classified_events", lambda main_db: events)
    index = pd.bdate_range("2026-07-01", periods=14)
    panel = PricePanel(pd.DataFrame({"AAPL": 100.0, "SPY": 500.0}, index=index))
    monkeypatch.setattr(runner, "load_price_history", lambda *a, **k: panel)

    runner.run_swing(db, str(tmp_path / "main.db"), now=NOW)
    book = load_book(db, "swing")
    assert book is not None and list(book.positions) == ["AAPL"]
    assert book.benchmark_entry_price == pytest.approx(500.0)
    trades = load_trades(db, "swing")
    assert trades[0]["reason"] == "event: beat"
    assert get_lane_state(db, "swing", "events_seen_until") == "2026-07-20T14:00:00+00:00"

    # second run with no NEW events: nothing bought again
    runner.run_swing(db, str(tmp_path / "main.db"), now=NOW)
    assert len(load_trades(db, "swing")) == 1


def test_session_lane_outside_market_window_is_a_no_op(db, monkeypatch) -> None:
    monkeypatch.setattr(runner, "within_market_window", lambda now: False)
    runner.run_session(db, now=NOW)
    assert load_book(db, "session") is None


def test_session_overnight_sweep_flattens_leftover_positions(db, monkeypatch) -> None:
    from equity_scout.shortterm_book import LaneBook, LanePosition
    from equity_scout.shortterm_storage import save_book

    stuck = LaneBook(
        lane="session", initial_capital=10_000.0, cash=8_500.0, benchmark_ticker="SPY",
        positions={"META": LanePosition(qty=2.0, entry_price=650.0, opened_at="t0")},
    )
    save_book(db, stuck, updated_at="t0")
    index = pd.date_range("2026-07-20 15:45", periods=1, freq="15min", tz="America/New_York")
    last_bar = pd.DataFrame([(648, 649, 647, 648.5)], index=index,
                            columns=["open", "high", "low", "close"])
    monkeypatch.setattr(runner, "within_market_window", lambda now: False)
    monkeypatch.setattr(runner, "fetch_bars", lambda tickers: {"META": last_bar})
    monkeypatch.setattr(runner, "settled_bars", lambda b, now: b)

    runner.run_session(db, now=NOW)
    book = load_book(db, "session")
    assert book is not None and book.positions == {}
    trades = load_trades(db, "session")
    assert trades[0]["side"] == "sell" and "Nachlauf" in trades[0]["reason"]


def test_session_lane_books_orb_fills_from_faked_bars(db, monkeypatch) -> None:
    monkeypatch.setattr(runner, "within_market_window", lambda now: True)
    index = pd.date_range("2026-07-20 09:30", periods=4, freq="15min", tz="America/New_York")
    bars = pd.DataFrame(
        [(100, 101, 99, 100), (100, 102, 98, 101), (101, 103, 100, 102.5), (103, 104, 102.5, 103.5)],
        index=index, columns=["open", "high", "low", "close"],
    )
    monkeypatch.setattr(runner, "fetch_bars", lambda tickers: {"SPY": bars})
    monkeypatch.setattr(runner, "settled_bars", lambda b, now: b)  # everything settled

    runner.run_session(db, now=NOW)
    book = load_book(db, "session")
    assert book is not None and "SPY" in book.positions
    trades = load_trades(db, "session")
    assert trades[0]["side"] == "buy" and trades[0]["reason"] == "ORB-Ausbruch"

    runner.run_session(db, now=NOW)  # same bars -> marker makes it a no-op
    assert len(load_trades(db, "session")) == 1
