"""Runner lanes end-to-end with faked feeds: fills persisted, markers, idempotency."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import scripts.run_shortterm as runner
from equity_scout.market import PricePanel
from equity_scout.shortterm_book import LaneBook, LanePosition
from equity_scout.shortterm_storage import (
    get_lane_state,
    load_book,
    load_trades,
    load_valuations,
    save_book,
    set_lane_state,
)

NOW = datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "shortterm.db")


def _crypto_bars(closes: list[float]) -> pd.DataFrame:
    # Daily bars: the lane's timescale since 2026-08-10 (see st_crypto's docstring).
    index = pd.date_range("2026-07-20 00:00", periods=len(closes), freq="1D", tz="UTC")
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
         "close": closes},
        index=index,
    )


def test_crypto_lane_books_a_breakout_and_is_idempotent(db) -> None:
    # completed_bars drops the running last row -> the judged signal bar is the 105 close
    bars = _crypto_bars([100.0] * 21 + [105.0, 106.0])

    def fake_fetch(pair, *, interval=None):  # noqa: ANN001, ANN202
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


def test_crypto_lane_requests_daily_bars(db) -> None:
    """Regression for the 2026-08-10 rebuild: on 15-minute bars the expected move per trade
    was smaller than the ~180 bps of round-trip friction the lane has to clear."""
    from equity_scout.kraken_data import DAILY_INTERVAL_MINUTES

    seen: list[int] = []

    def fake_fetch(pair, *, interval):  # noqa: ANN001, ANN202
        seen.append(interval)
        return None

    runner.run_crypto(db, now=NOW, fetch=fake_fetch)
    assert seen and set(seen) == {DAILY_INTERVAL_MINUTES}


def test_crypto_lane_stamps_the_strategy_regime_break_once(db) -> None:
    bars = _crypto_bars([100.0] * 21 + [105.0, 106.0])

    def fake_fetch(pair, *, interval=None):  # noqa: ANN001, ANN202
        return bars if pair == "XBTUSD" else None

    runner.run_crypto(db, now=NOW, fetch=fake_fetch)
    stamped = get_lane_state(db, "crypto", runner.STRATEGY_REGIME_KEY)
    assert stamped == NOW.isoformat(timespec="seconds")

    later = datetime(2026, 7, 21, 18, 0, tzinfo=timezone.utc)
    runner.run_crypto(db, now=later, fetch=fake_fetch)
    assert get_lane_state(db, "crypto", runner.STRATEGY_REGIME_KEY) == stamped  # never moves


def test_switching_timescale_drops_the_old_bar_watermarks(db) -> None:
    """A 15-minute watermark is NEWER than the newest completed daily bar, so keeping it
    would block every decision until the wall clock passed it (seen on the first live daily
    run, 2026-08-10: the lane judged nothing and reported 0 fills)."""
    from equity_scout.shortterm_storage import set_lane_state as _set

    _set(db, "crypto", "last_bar_BTC", "2026-08-10T17:00:00+00:00")  # 15-minute era
    bars = _crypto_bars([100.0] * 21 + [105.0, 106.0])  # last completed bar: 2026-08-09
    runner.run_crypto(
        db, now=NOW, fetch=lambda pair, *, interval=None: bars if pair == "XBTUSD" else None
    )
    # The stale watermark is gone and the daily breakout was actually judged and booked.
    trades = load_trades(db, "crypto")
    assert len(trades) == 1 and trades[0]["side"] == "buy"


def test_crypto_fills_carry_the_kraken_taker_fee(db) -> None:
    """The lane simulates Kraken; its lowest published taker tier is 0.80% per side. A 0-fee
    book would measure a strategy that no reachable venue offers (found 2026-08-09: the lane
    had been charged slippage only, understating round-trip costs by ~160 bps). Not lowered
    to the 0.40% maker rate in the 2026-08-10 rebuild: the lane routes nothing, and a limit
    order at the breakout level is exactly the one that does not fill when it breaks."""
    bars = _crypto_bars([100.0] * 21 + [105.0, 106.0])
    runner.run_crypto(db, now=NOW,
                      fetch=lambda pair, *, interval=None: bars if pair == "XBTUSD" else None)
    trade = load_trades(db, "crypto")[0]
    spend = 10_000.0 * runner.CRYPTO_FRACTION
    fee = spend * runner.CRYPTO_FEE_BPS / 10_000.0
    effective = 105.0 * (1.0 + runner.CRYPTO_SLIPPAGE_BPS / 10_000.0)
    slip_cost = trade["qty"] * (effective - 105.0)
    assert fee > 0
    assert trade["qty"] == pytest.approx((spend - fee) / effective)
    assert trade["fees"] == pytest.approx(fee + slip_cost)


def test_crypto_lane_skips_honestly_when_feed_is_down(db) -> None:
    runner.run_crypto(db, now=NOW, fetch=lambda pair, *, interval=None: None)
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


def test_swing_lane_frees_slots_before_entering(db, tmp_path, monkeypatch) -> None:
    """v13 R7: an exit due today frees its slot for today's entries — and the exited
    ticker itself must not re-enter on the same close it just exited on, even when its
    event is the freshest in the pool (churn guard)."""
    held = [f"T{i}" for i in range(8)]  # book at MAX_POSITIONS
    positions = {
        t: LanePosition(qty=10.0, entry_price=100.0, opened_at="2026-07-18T20:00:00+00:00")
        for t in held
    }
    book = LaneBook(lane="swing", initial_capital=10_000.0, cash=2_000.0,
                    benchmark_ticker="SPY", positions=positions)
    save_book(db, book, updated_at="2026-07-18")
    set_lane_state(db, "swing", "events_seen_until", "2026-07-19T00:00:00+00:00")

    events = [
        # fresher event for the exiting ticker: without the churn guard it wins the slot
        {"ticker": "T0", "event_type": "beat", "seen_at": "2026-07-20T15:00:00+00:00"},
        {"ticker": "NEWT", "event_type": "beat", "seen_at": "2026-07-20T14:00:00+00:00"},
    ]
    monkeypatch.setattr(runner, "load_classified_events", lambda main_db: events)
    index = pd.bdate_range("2026-07-06", periods=11)  # last business day = 2026-07-20
    columns = {t: 100.0 for t in held} | {"T0": 106.0, "NEWT": 50.0, "SPY": 500.0}
    panel = PricePanel(pd.DataFrame(columns, index=index))
    monkeypatch.setattr(runner, "load_price_history", lambda *a, **k: panel)

    runner.run_swing(db, str(tmp_path / "main.db"), now=NOW)
    book = load_book(db, "swing")
    assert book is not None
    assert "T0" not in book.positions  # +6% profit-target exit booked first...
    assert "NEWT" in book.positions  # ...and today's entry filled the freed slot
    sides = {(t["side"], t["ticker"]) for t in load_trades(db, "swing")}
    assert ("sell", "T0") in sides
    assert ("buy", "NEWT") in sides
    assert ("buy", "T0") not in sides  # no same-day re-entry churn


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


def test_session_lane_force_flats_stale_position_before_deciding(db, monkeypatch) -> None:
    """R1/P0 (review 2026-07-20): a position carried over from a previous day must be
    closed at today's first settled open — NEVER managed with today's opening range."""
    from equity_scout.shortterm_book import LaneBook, LanePosition
    from equity_scout.shortterm_storage import save_book

    stale = LaneBook(
        lane="session", initial_capital=10_000.0, cash=8_700.0, benchmark_ticker="SPY",
        positions={"META": LanePosition(qty=2.0, entry_price=650.0,
                                        opened_at="2026-07-17T14:00:00-04:00")},
    )
    save_book(db, stale, updated_at="2026-07-17T20:00:00+00:00")
    index = pd.date_range("2026-07-20 09:30", periods=4, freq="15min", tz="America/New_York")
    # today's range (102/98) would put the stale position's "stop" at 648 — buggy fill
    bars = pd.DataFrame(
        [(100, 101, 99, 100), (100, 102, 98, 101), (95, 96, 90, 92), (93, 94, 92, 93.5)],
        index=index, columns=["open", "high", "low", "close"],
    )
    monkeypatch.setattr(runner, "within_market_window", lambda now: True)
    monkeypatch.setattr(runner, "fetch_bars", lambda tickers: {"META": bars})
    monkeypatch.setattr(runner, "settled_bars", lambda b, now: b)

    runner.run_session(db, now=NOW)
    book = load_book(db, "session")
    assert book is not None and "META" not in book.positions
    sells = [t for t in load_trades(db, "session") if t["side"] == "sell"]
    assert len(sells) == 1
    assert "Altbestand" in sells[0]["reason"]
    # first settled open (minus 5 bps slippage convention), NOT the range-derived 648
    assert sells[0]["price"] == pytest.approx(100.0 * (1 - 0.0005))


def test_session_lane_keeps_fresh_same_day_position(db, monkeypatch) -> None:
    from equity_scout.shortterm_book import LaneBook, LanePosition
    from equity_scout.shortterm_storage import save_book

    fresh = LaneBook(
        lane="session", initial_capital=10_000.0, cash=9_800.0, benchmark_ticker="SPY",
        positions={"SPY": LanePosition(qty=2.0, entry_price=100.0,
                                       opened_at="2026-07-20T09:45:00-04:00")},
    )
    save_book(db, fresh, updated_at="2026-07-20T13:45:00+00:00")
    index = pd.date_range("2026-07-20 09:30", periods=3, freq="15min", tz="America/New_York")
    bars = pd.DataFrame(  # nothing triggers: no stop, no target, well before the last bar
        [(100, 101, 99, 100), (100, 101.5, 99.5, 100.5), (100.5, 101, 100, 100.8)],
        index=index, columns=["open", "high", "low", "close"],
    )
    monkeypatch.setattr(runner, "within_market_window", lambda now: True)
    monkeypatch.setattr(runner, "fetch_bars", lambda tickers: {"SPY": bars})
    monkeypatch.setattr(runner, "settled_bars", lambda b, now: b)

    runner.run_session(db, now=NOW)
    book = load_book(db, "session")
    assert book is not None and "SPY" in book.positions
    assert load_trades(db, "session") == []


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


def test_swing_lane_persists_its_rejections(db, tmp_path, monkeypatch) -> None:
    """The no-trade book: the run writes why candidates were NOT traded — the bearish
    headline as not_bullish, the quoteless event ticker as no_quote — and a re-run over
    the same inputs does not double-count them."""
    from equity_scout.shortterm_storage import load_open_rejections

    events = [
        {"ticker": "AAPL", "event_type": "beat", "seen_at": "2026-07-20T14:00:00+00:00"},
        {"ticker": "MSFT", "event_type": "miss", "seen_at": "2026-07-20T14:00:00+00:00",
         "detail": "MSFT misses on revenue"},
        {"ticker": "NOQT", "event_type": "beat", "seen_at": "2026-07-20T14:30:00+00:00"},
    ]
    monkeypatch.setattr(runner, "load_classified_events", lambda main_db: events)
    index = pd.bdate_range("2026-07-01", periods=14)
    panel = PricePanel(pd.DataFrame({"AAPL": 100.0, "SPY": 500.0}, index=index))
    monkeypatch.setattr(runner, "load_price_history", lambda *a, **k: panel)

    runner.run_swing(db, str(tmp_path / "main.db"), now=NOW)
    rows = {r["ticker"]: r for r in load_open_rejections(db, "swing")}
    assert rows["MSFT"]["reason"] == "not_bullish"
    assert "misses on revenue" in rows["MSFT"]["detail"]
    assert rows["NOQT"]["reason"] == "no_quote"
    assert rows["NOQT"]["seen_at"] == "2026-07-20T14:30:00+00:00"
    assert "AAPL" not in rows  # traded, not rejected

    monkeypatch.setattr(runner, "load_classified_events", lambda main_db: events)
    runner.run_swing(db, str(tmp_path / "main.db"), now=NOW)
    assert len(load_open_rejections(db, "swing")) == 2


GAPFADE_SIGNAL_NOW = datetime(2026, 8, 17, 13, 20, tzinfo=timezone.utc)  # Mon 09:20 ET


def _accepted_order(order_id: str):
    from equity_scout.alpaca_broker import BrokerOrder

    return BrokerOrder(order_id=order_id, status="accepted", filled_qty=0.0,
                       filled_avg_price=None)


def _filled_order(order_id: str, qty: float, price: float):
    from equity_scout.alpaca_broker import BrokerOrder

    return BrokerOrder(order_id=order_id, status="filled", filled_qty=qty,
                       filled_avg_price=price)


def test_gapfade_places_moo_orders_once_and_logs_calibration_rows(db, tmp_path, monkeypatch) -> None:
    """Phase 1: inside the 09:00-09:28 ET window the lane sizes against the book, places
    market-on-open orders for deep gaps, logs sub-threshold gaps into the no-trade book,
    and a second run the same day is a no-op (day marker)."""
    import json as jsonlib

    from equity_scout.market import PricePanel
    from equity_scout.shortterm_storage import get_lane_state, load_open_rejections

    monkeypatch.setattr(runner, "tracked_tickers", lambda db_path: {"DOWN", "NEAR"})
    index = pd.bdate_range("2026-08-03", periods=10)  # ends Fri 2026-08-14
    panel = PricePanel(pd.DataFrame({"DOWN": 100.0, "NEAR": 100.0, "SPY": 500.0}, index=index))
    monkeypatch.setattr(runner, "load_price_history", lambda *a, **k: panel)
    fresh = GAPFADE_SIGNAL_NOW - timedelta(minutes=3)
    monkeypatch.setattr(runner, "fetch_latest_trades",
                        lambda tickers: {"DOWN": (97.0, fresh), "NEAR": (98.5, fresh)})
    placed: list[tuple] = []

    def fake_place(ticker, *, qty, side, auction):
        placed.append((ticker, qty, side, auction))
        return _accepted_order("moo-1")

    monkeypatch.setattr(runner, "place_auction_order", fake_place)

    runner.run_gapfade(db, str(tmp_path / "main.db"), now=GAPFADE_SIGNAL_NOW)
    assert placed == [("DOWN", 15, "buy", "opg")]  # int(0.15 * 10_000 / 97.0)
    rows = load_open_rejections(db, "gapfade")
    assert [r["reason"] for r in rows] == ["below_threshold"]
    assert get_lane_state(db, "gapfade", runner.GAPFADE_DAY_KEY) == "2026-08-17"
    entry_orders = jsonlib.loads(get_lane_state(db, "gapfade", runner.GAPFADE_ENTRY_ORDERS_KEY))
    assert entry_orders[0]["order_id"] == "moo-1"
    assert entry_orders[0]["signal_price"] == pytest.approx(97.0)

    runner.run_gapfade(db, str(tmp_path / "main.db"), now=GAPFADE_SIGNAL_NOW)
    assert len(placed) == 1  # day marker: no second submission


def test_gapfade_asks_alpaca_only_about_us_listings(db, tmp_path, monkeypatch) -> None:
    """The bug that cost the lane its first four trading days (2026-08-17..20): the
    watchlist is global, Alpaca is not. One `0006.HK` in the batch answered 400 for ALL
    symbols, so `fetch_latest_trades` raised, the day marker was never set, and every
    5-minute rerun repeated it — a lane that looked idle while it was actually broken.
    The foreign names must be gone before the request, and before the price panel."""
    import json as jsonlib

    from equity_scout.market import PricePanel
    from equity_scout.shortterm_storage import get_lane_state

    tracked = {"DOWN", "0006.HK", "ALV.DE", "9984.T", "PETR4.SA"}
    monkeypatch.setattr(runner, "tracked_tickers", lambda db_path: tracked)
    index = pd.bdate_range("2026-08-03", periods=10)
    panel = PricePanel(pd.DataFrame({"DOWN": 100.0, "SPY": 500.0}, index=index))
    panel_calls: list[list[str]] = []

    def fake_panel(tickers, **kwargs):
        panel_calls.append(list(tickers))
        return panel

    monkeypatch.setattr(runner, "load_price_history", fake_panel)
    asked: list[list[str]] = []
    fresh = GAPFADE_SIGNAL_NOW - timedelta(minutes=3)

    def fake_trades(tickers):
        asked.append(list(tickers))
        return {"DOWN": (97.0, fresh)}

    monkeypatch.setattr(runner, "fetch_latest_trades", fake_trades)
    monkeypatch.setattr(runner, "place_auction_order",
                        lambda ticker, *, qty, side, auction: _accepted_order("moo-1"))

    runner.run_gapfade(db, str(tmp_path / "main.db"), now=GAPFADE_SIGNAL_NOW)

    assert asked == [["DOWN"]]  # no foreign listing survives into the request
    assert panel_calls == [["DOWN", "SPY"]]  # nor into the download
    assert get_lane_state(db, "gapfade", runner.GAPFADE_DAY_KEY) == "2026-08-17"
    orders = jsonlib.loads(get_lane_state(db, "gapfade", runner.GAPFADE_ENTRY_ORDERS_KEY))
    assert [o["ticker"] for o in orders] == ["DOWN"]


def test_gapfade_without_a_single_us_listing_marks_the_day_instead_of_asking(
    db, tmp_path, monkeypatch
) -> None:
    """An all-foreign watchlist is a real state, not an error: mark the day, say so, and
    do not spend a request. Without the marker the 5-minute cron would retry all morning."""
    from equity_scout.shortterm_storage import get_lane_state

    monkeypatch.setattr(runner, "tracked_tickers", lambda db_path: {"0006.HK", "ALV.DE"})

    def explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("asked Alpaca about a foreign listing")

    monkeypatch.setattr(runner, "fetch_latest_trades", explode)
    monkeypatch.setattr(runner, "load_price_history", explode)

    runner.run_gapfade(db, str(tmp_path / "main.db"), now=GAPFADE_SIGNAL_NOW)
    assert get_lane_state(db, "gapfade", runner.GAPFADE_DAY_KEY) == "2026-08-17"


def test_gapfade_books_the_auction_fill_and_places_the_close(db, tmp_path, monkeypatch) -> None:
    """Phase 2: the OPG fill is booked with the BROKER's quantity and price, the
    signal-vs-fill drift lands in st_executions (the lane's core measurement), and a
    market-on-close order takes over the exit."""
    import json as jsonlib

    from equity_scout.shortterm_storage import get_lane_state, load_executions, set_lane_state

    set_lane_state(db, "gapfade", runner.GAPFADE_DAY_KEY, "2026-08-17")
    set_lane_state(db, "gapfade", runner.GAPFADE_ENTRY_ORDERS_KEY, jsonlib.dumps([{
        "order_id": "moo-1", "ticker": "DOWN", "signal_price": 97.0,
        "signalled_at": "2026-08-17T13:20:00+00:00", "reason": "Gap -3.0% (Fade)",
    }]))
    monkeypatch.setattr(runner, "fetch_order", lambda oid: _filled_order(oid, 15.0, 96.8))
    placed: list[tuple] = []

    def fake_place(ticker, *, qty, side, auction):
        placed.append((ticker, qty, side, auction))
        return _accepted_order("moc-1")

    monkeypatch.setattr(runner, "place_auction_order", fake_place)

    later = datetime(2026, 8, 17, 14, 5, tzinfo=timezone.utc)  # 10:05 ET
    runner.run_gapfade(db, str(tmp_path / "main.db"), now=later)
    book = load_book(db, "gapfade")
    assert book is not None and book.positions["DOWN"].qty == 15.0
    assert book.positions["DOWN"].entry_price == pytest.approx(96.8)
    assert placed == [("DOWN", 15.0, "sell", "cls")]
    execution = load_executions(db, "gapfade")[0]
    assert execution["expected_price"] == pytest.approx(97.0)
    assert execution["actual_price"] == pytest.approx(96.8)
    assert jsonlib.loads(get_lane_state(db, "gapfade", runner.GAPFADE_ENTRY_ORDERS_KEY)) == []
    exit_orders = jsonlib.loads(get_lane_state(db, "gapfade", runner.GAPFADE_EXIT_ORDERS_KEY))
    assert exit_orders[0]["order_id"] == "moc-1"


def test_gapfade_settles_the_closing_auction(db, tmp_path, monkeypatch) -> None:
    """Phase 3 (nightly): the CLS fill flattens the book, books realised P&L and writes a
    valuation row."""
    import json as jsonlib

    from equity_scout.shortterm_book import buy as book_buy
    from equity_scout.shortterm_storage import get_lane_state, save_book, set_lane_state

    book = LaneBook.fresh("gapfade", benchmark_ticker="SPY")
    book, _ = book_buy(book, "DOWN", 96.8, "2026-08-17T13:31:00+00:00",
                       fraction=0.15, reason="Gap", slippage_bps=0.0, qty=15.0)
    save_book(db, book, updated_at="2026-08-17")
    set_lane_state(db, "gapfade", runner.GAPFADE_EXIT_ORDERS_KEY, jsonlib.dumps([{
        "order_id": "moc-1", "ticker": "DOWN",
        "signalled_at": "2026-08-17T14:05:00+00:00",
    }]))
    monkeypatch.setattr(runner, "fetch_order", lambda oid: _filled_order(oid, 15.0, 98.0))
    from equity_scout.market import PricePanel

    index = pd.bdate_range("2026-08-10", periods=6)
    spy_panel = PricePanel(pd.DataFrame({"SPY": 500.0}, index=index))
    monkeypatch.setattr(runner, "load_price_history", lambda *a, **k: spy_panel)

    nightly = datetime(2026, 8, 18, 0, 30, tzinfo=timezone.utc)
    runner.run_gapfade(db, str(tmp_path / "main.db"), now=nightly)
    book = load_book(db, "gapfade")
    assert book is not None and book.positions == {}
    assert book.benchmark_entry_price == pytest.approx(500.0)
    sells = [t for t in load_trades(db, "gapfade") if t["side"] == "sell"]
    assert len(sells) == 1
    assert sells[0]["realized_pnl"] == pytest.approx(15.0 * (98.0 - 96.8))
    assert jsonlib.loads(get_lane_state(db, "gapfade", runner.GAPFADE_EXIT_ORDERS_KEY)) == []
    assert len(load_valuations(db, "gapfade")) == 1
