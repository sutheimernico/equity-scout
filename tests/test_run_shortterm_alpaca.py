"""The 2026-07-21 outage rule, stated as code: whoever cannot show they were here a bar ago
does not open a new position. Exits stay allowed — abandoning an open position is worse
than any entry rule."""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import scripts.run_shortterm as runner
from equity_scout.alpaca_broker import (
    AlpacaBrokerError,
    BrokerFill,
    BrokerOrder,
    BrokerPosition,
)
from equity_scout.alpaca_data import RANGE_BAR_MINUTES, TRIGGER_BAR_MINUTES
from equity_scout.shortterm_storage import init_shortterm_db, load_executions, set_lane_state

NY = ZoneInfo("America/New_York")
may_open_new_position = runner.may_open_new_position


def test_a_run_one_cadence_after_the_last_one_may_open() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    last = (now - timedelta(minutes=1)).isoformat()
    assert may_open_new_position(last_run=last, now=now) is True


def test_a_gap_of_more_than_the_tolerance_blocks_new_entries() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    last = (now - timedelta(minutes=40)).isoformat()
    assert may_open_new_position(last_run=last, now=now) is False


def test_the_very_first_run_may_open() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    assert may_open_new_position(last_run=None, now=now) is True


def test_the_tolerance_is_the_callers_to_set() -> None:
    """The gate measures "did the machine miss slots", so its tolerance belongs to the
    cadence, not to the bar length. The lane runs every 15 minutes today and every minute
    after Task 9; the same gap must be readable as fine under one and as a gap under the
    other, which a hardcoded constant cannot express.
    """
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    last = (now - timedelta(minutes=12)).isoformat()
    assert may_open_new_position(last_run=last, now=now, max_gap=timedelta(minutes=22)) is True
    assert may_open_new_position(last_run=last, now=now, max_gap=timedelta(minutes=5)) is False


def test_the_default_tolerance_matches_the_one_minute_cadence() -> None:
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    assert runner.MAX_RUN_GAP == timedelta(minutes=5)
    assert may_open_new_position(
        last_run=(now - timedelta(minutes=4, seconds=59)).isoformat(), now=now
    ) is True
    assert may_open_new_position(
        last_run=(now - timedelta(minutes=5, seconds=1)).isoformat(), now=now
    ) is False


def test_a_last_run_stamp_from_the_future_does_not_unlock_entries() -> None:
    """Clock skew or a repaired state file must not read as "we were just here". The
    2026-07-24 Tokyo-timestamp incident is precisely a future as_of slipping into state.
    """
    now = datetime(2026, 8, 4, 10, 15, tzinfo=NY)
    ahead = (now + timedelta(hours=3)).isoformat()
    assert may_open_new_position(last_run=ahead, now=now) is False


# --- Task 9 Step 1: the quiet run ------------------------------------------------------


def test_a_run_that_changed_nothing_reports_nothing() -> None:
    """Prerequisite for the one-minute cadence. At */15 a report block per run is 26 lines
    a day and all of them worth reading; at * * * * * it is ~390, and that is how the two
    production bugs this project already hit stayed invisible in the log.
    """
    assert runner.session_report_due(fills=[], first_run_of_day=False) is False


def test_a_fill_is_always_reported() -> None:
    assert runner.session_report_due(fills=["a fill"], first_run_of_day=False) is True


def test_the_first_run_of_the_day_is_reported_even_without_fills() -> None:
    """One anchor line per session proves the lane ran at all — otherwise a lane that died
    at 09:30 and a lane that simply found no setup look identical in the log."""
    assert runner.session_report_due(fills=[], first_run_of_day=True) is True


# --- Task 6: the broker path inside run_session -------------------------------------------
# Two resolutions, two roles (design decision 5): 15-minute bars build the opening range,
# 1-minute bars carry the breakout trigger. The fakes below answer per resolution, exactly
# as alpaca_data.fetch_bars does.


def _range_bars() -> pd.DataFrame:
    """09:30 + 09:45 -> opening range high 102, low 100."""
    index = pd.date_range("2026-08-04 09:30", periods=2, freq="15min", tz=NY)
    return pd.DataFrame(
        {"open": [100.0, 101.0], "high": [102.0, 102.0], "low": [100.0, 100.5],
         "close": [101.0, 101.5], "volume": [1000, 1000]},
        index=index,
    )


def _trigger_bars() -> pd.DataFrame:
    """The 10:02 bar closes at 103 — above the range high — and the 10:03 bar opens at 103,
    which is the fill. Two bars lead in because `decide` treats the first two as the range."""
    index = pd.date_range("2026-08-04 10:00", periods=4, freq="1min", tz=NY)
    return pd.DataFrame(
        {"open": [101.5, 101.8, 102.2, 103.0], "high": [101.9, 102.0, 103.2, 103.4],
         "low": [101.4, 101.6, 102.1, 102.9], "close": [101.8, 102.0, 103.0, 103.2],
         "volume": [500] * 4},
        index=index,
    )


def _fake_feed(tickers, *, now, bar_minutes, **_kwargs):
    frame = _range_bars() if bar_minutes == RANGE_BAR_MINUTES else _trigger_bars()
    assert bar_minutes in (RANGE_BAR_MINUTES, TRIGGER_BAR_MINUTES)
    return {"AAPL": frame}


def test_a_breakout_places_a_bracket_order_and_books_the_broker_fill(tmp_path, monkeypatch):
    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    placed: dict = {}

    def fake_place(ticker, *, qty, stop_price, target_price):
        placed.update(ticker=ticker, qty=qty, stop=stop_price, target=target_price)
        return BrokerOrder(order_id="o1", status="filled", filled_qty=float(int(qty)),
                           filled_avg_price=103.12)

    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "place_bracket", fake_place)

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    assert placed["ticker"] == "AAPL"
    # entry 103.0, range 2.0 -> stop 102.0, target 105.0
    assert placed["stop"] == pytest.approx(102.0)
    assert placed["target"] == pytest.approx(105.0)
    rows = load_executions(db_path, lane="session")
    assert rows[0]["expected_price"] == pytest.approx(103.0)
    # The MEASURED price is the broker's, not the signal's — this is the whole point.
    assert rows[0]["actual_price"] == pytest.approx(103.12)


def test_the_valuation_carries_the_brokers_own_equity(tmp_path, monkeypatch):
    """The book runs a 10k ledger while the paper account holds 100k, so the same trades read
    as -2.41% and -0.10% (measured 2026-08-10). The valuation therefore records what the venue
    itself reports instead of leaving the reader to divide by the wrong denominator."""
    from equity_scout.alpaca_broker import BrokerAccount
    from equity_scout.shortterm_storage import load_valuations

    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "place_bracket", lambda *a, **k: BrokerOrder(
        order_id="o1", status="filled", filled_qty=1.0, filled_avg_price=103.12))
    monkeypatch.setattr(runner, "fetch_account", lambda: BrokerAccount(
        equity=99_904.61, last_equity=99_925.41, cash=98_890.92))

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    rows = load_valuations(db_path, "session")
    assert rows and rows[-1]["broker_equity"] == pytest.approx(99_904.61)


def test_a_broker_outage_costs_the_valuation_its_account_number_not_the_row(
    tmp_path, monkeypatch, capsys
):
    """A hiccup at the venue must never cost the lane its valuation row — None over raising."""
    from equity_scout.alpaca_broker import AlpacaBrokerError, BrokerOrder as _Order
    from equity_scout.shortterm_storage import load_valuations

    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "place_bracket", lambda *a, **k: _Order(
        order_id="o1", status="filled", filled_qty=1.0, filled_avg_price=103.12))

    def boom():
        raise AlpacaBrokerError("GET /v2/account -> 503")

    monkeypatch.setattr(runner, "fetch_account", boom)
    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    rows = load_valuations(db_path, "session")
    assert rows and rows[-1]["broker_equity"] is None
    assert "Konto-Equity nicht abrufbar" in capsys.readouterr().out


def test_a_simulated_lane_never_calls_the_broker_for_equity(tmp_path, monkeypatch) -> None:
    """`feed != "alpaca"` must not reach the venue at all — the yfinance path has no account."""
    def explode():
        raise AssertionError("the simulated path must not ask the broker for an account")

    monkeypatch.setattr(runner, "fetch_account", explode)
    assert runner._broker_equity("yfinance") is None


def test_the_book_records_the_broker_price_not_the_signal_price(tmp_path, monkeypatch):
    """Slippage is not modelled on top of a real fill: the broker price already contains it."""
    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "place_bracket",
                        lambda t, **k: BrokerOrder("o9", "filled", 1.0, 103.5))

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    from equity_scout.shortterm_storage import load_book

    book = load_book(db_path, "session")
    assert book is not None
    assert book.positions["AAPL"].entry_price == pytest.approx(103.5)


def test_a_divergence_is_reported_and_does_not_silently_merge(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(
        runner, "fetch_broker_positions",
        lambda: {"TSLA": BrokerPosition("TSLA", 4.0, 330.0)},
    )
    monkeypatch.setattr(runner, "place_bracket",
                        lambda t, **k: BrokerOrder("o2", "filled", 1.0, 103.0))

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")
    captured = capsys.readouterr()
    assert "ABWEICHUNG" in captured.err and "TSLA" in captured.err


def test_a_stale_run_manages_positions_but_opens_nothing(tmp_path, monkeypatch):
    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    set_lane_state(db_path, "session", runner.LAST_RUN_KEY,
                   datetime(2026, 8, 4, 9, 0, tzinfo=NY).isoformat())
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)

    def refuse(*args, **kwargs):
        raise AssertionError("no entry may be placed after a run gap")

    monkeypatch.setattr(runner, "place_bracket", refuse)
    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")


def test_a_rejected_order_leaves_the_book_flat(tmp_path, monkeypatch, capsys):
    """A refused order must not leave a position the broker does not hold."""
    from equity_scout.alpaca_broker import AlpacaBrokerError
    from equity_scout.shortterm_storage import load_book

    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)

    def reject(*args, **kwargs):
        raise AlpacaBrokerError("insufficient buying power")

    monkeypatch.setattr(runner, "place_bracket", reject)
    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    book = load_book(db_path, "session")
    assert book is None or book.positions == {}
    assert "abgelehnt" in capsys.readouterr().err.lower()


def test_missing_keys_fall_back_to_yfinance_loudly(tmp_path, monkeypatch, capsys):
    """A broken key must degrade to the old path, not stop the lane silently."""
    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.setattr(runner, "fetch_bars", lambda tickers: {})

    def forbidden(*args, **kwargs):
        raise AssertionError("the Alpaca feed must not be called without keys")

    monkeypatch.setattr(runner, "alpaca_fetch_bars", forbidden)
    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")
    assert "yfinance" in capsys.readouterr().err


# --- Task 9: the log has to survive 390 runs a day ----------------------------------------

def test_a_silent_session_run_prints_no_header_and_no_disclaimer(monkeypatch, capsys):
    """At `* * * * *` the CLI's own framing is the noise: 390 headers plus 390 disclaimers a
    day is how the two production bugs of 2026-07 stayed invisible in intraday.log."""
    monkeypatch.setattr(sys, "argv", ["run_shortterm.py", "--lane", "session"])
    monkeypatch.setattr(runner, "run_session", lambda db, *, now: None)
    runner.main()
    assert capsys.readouterr().out == ""


def test_a_session_run_with_something_to_say_is_framed_as_before(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run_shortterm.py", "--lane", "session"])
    monkeypatch.setattr(runner, "run_session", lambda db, *, now: print("Session: 1 Fill"))
    runner.main()
    out = capsys.readouterr().out
    assert "Kurzfrist-Arena" in out and "Session: 1 Fill" in out and "Anlageberatung" in out


def test_a_blocked_entry_does_not_send_its_stop_to_the_broker(tmp_path, monkeypatch):
    """Found on the first live run, 2026-08-06 10:31 ET.

    `decide` can emit buy AND sell for the same bar (an entry whose own bar trades through the
    stop). With entries blocked the buy is dropped — and the sell was still routed, so the lane
    asked the broker to close a position it had never opened (`404 position not found: SPY`).
    An exit without a holding must never reach the broker.
    """
    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    # Stale stamp -> may_open_new_position() is False, exactly as on the cold start.
    set_lane_state(db_path, "session", runner.LAST_RUN_KEY,
                   datetime(2026, 8, 4, 9, 0, tzinfo=NY).isoformat())

    def entry_then_stop(ticker, bars, position, **kwargs):
        at = "2026-08-04T10:03:00-04:00"
        return (
            [runner.SessionAction("buy", ticker, 103.0, at, "ORB-Ausbruch"),
             runner.SessionAction("sell", ticker, 102.0, at, "Stop (0.5x Range)")],
            at,
        )

    def refuse_close(ticker):
        raise AssertionError("no exit may be routed for a position the book does not hold")

    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "decide", entry_then_stop)
    monkeypatch.setattr(runner, "close_position", refuse_close)
    monkeypatch.setattr(runner, "place_bracket",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no entry either")))

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")


def test_a_pending_order_is_read_back_before_it_is_booked(tmp_path, monkeypatch):
    """The realistic path: the POST says `pending_new`, the fill arrives right after."""
    from equity_scout.shortterm_storage import load_book

    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "place_bracket",
                        lambda t, **k: BrokerOrder("o5", "pending_new", 0.0, None))
    monkeypatch.setattr(runner, "settle_or_cancel",
                        lambda order: BrokerOrder("o5", "filled", 3.0, 103.4))

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    book = load_book(db_path, "session")
    assert book is not None and book.positions["AAPL"].entry_price == pytest.approx(103.4)
    assert load_executions(db_path, lane="session")[0]["actual_price"] == pytest.approx(103.4)


def test_an_order_that_stays_pending_leaves_the_book_flat(tmp_path, monkeypatch, capsys):
    from equity_scout.shortterm_storage import load_book

    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "place_bracket",
                        lambda t, **k: BrokerOrder("o6", "pending_new", 0.0, None))
    monkeypatch.setattr(runner, "settle_or_cancel",
                        lambda order: BrokerOrder("o6", "canceled", 0.0, None))

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    book = load_book(db_path, "session")
    assert book is None or book.positions == {}
    assert "storniert" in capsys.readouterr().err


def test_the_book_holds_exactly_what_the_broker_filled(tmp_path, monkeypatch):
    """The invariant that broke live on 2026-08-06: book 4.59188 TSLA, broker 4."""
    from equity_scout.shortterm_storage import load_book

    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "place_bracket",
                        lambda t, **k: BrokerOrder("o7", "filled", 4.0, 103.0))

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    book = load_book(db_path, "session")
    assert book is not None and book.positions["AAPL"].qty == 4.0


def _held_book(db_path: str, *, qty: float = 2.0, entry: float = 103.0) -> None:
    """A book holding TSLA from earlier in the session, as after a bracket entry.

    TSLA deliberately: the fake feed only serves AAPL, so `decide` never touches this
    position and the test measures the healing path instead of an ordinary bar exit.
    """
    from equity_scout.shortterm_book import LaneBook, LanePosition
    from equity_scout.shortterm_storage import persist_lane_step

    book = LaneBook.fresh("session", benchmark_ticker="SPY")
    book = replace(
        book,
        cash=book.cash - qty * entry,
        positions={"TSLA": LanePosition(qty=qty, entry_price=entry,
                                        opened_at="2026-08-04T10:03:00-04:00")},
    )
    persist_lane_step(db_path, book, updated_at="2026-08-04T10:03:00-04:00")


def test_a_bracket_leg_that_filled_in_the_market_is_booked_back(tmp_path, monkeypatch):
    """The 2026-08-07 META defect. The stop leg fires at the venue without us; the book kept
    holding a position the broker had closed, and eventually closed it at the SIGNAL price.
    The broker's own fill is the trade that happened, so that is what the book books."""
    from equity_scout.shortterm_storage import load_book, load_executions, load_trades

    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    _held_book(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)  # broker is flat
    monkeypatch.setattr(runner, "fetch_fills", lambda ticker, *, after: [
        BrokerFill(order_id="stop-1", ticker="TSLA", side="sell", qty=2.0, price=101.94,
                   at="2026-08-04T14:20:11Z", requested_price=102.0),
    ])

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    book = load_book(db_path, "session")
    assert book is not None and "TSLA" not in book.positions
    booked = [t for t in load_trades(db_path, lane="session") if t["side"] == "sell"]
    assert len(booked) == 1
    assert booked[0]["price"] == pytest.approx(101.94)  # the broker's price, not the signal's
    assert booked[0]["executed_at"] == "2026-08-04T14:20:11Z"
    executions = [e for e in load_executions(db_path, lane="session") if e["side"] == "sell"]
    assert len(executions) == 1
    # The leg asked 102.00 and got 101.94 — the slippage that was invisible until now.
    assert executions[0]["expected_price"] == pytest.approx(102.0)
    assert executions[0]["actual_price"] == pytest.approx(101.94)
    assert executions[0]["order_id"] == "stop-1"


def test_the_overnight_sweep_books_the_brokers_exit_too(tmp_path, monkeypatch):
    """Same defect, second door. After the close the sweep flattens whatever is still open —
    and if the broker's stop had already closed it, the sweep's own flatten answers 404 and
    the book records the last bar's close. The healing has to run on this path as well."""
    from equity_scout.shortterm_storage import load_book, load_trades

    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    _held_book(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "fetch_fills", lambda ticker, *, after: [
        BrokerFill(order_id="stop-9", ticker="TSLA", side="sell", qty=2.0, price=101.94,
                   at="2026-08-04T19:20:11Z", requested_price=102.0),
    ])

    # 17:10 New York — outside the market window, the sweep's slot.
    runner.run_session(db_path, now=datetime(2026, 8, 4, 17, 10, tzinfo=NY), feed="alpaca")

    book = load_book(db_path, "session")
    assert book is not None and "TSLA" not in book.positions
    sells = [t for t in load_trades(db_path, lane="session") if t["side"] == "sell"]
    assert len(sells) == 1
    assert sells[0]["price"] == pytest.approx(101.94)
    assert sells[0]["reason"] == "Broker-Bracket (nachgebucht)"


def test_an_unexplained_divergence_is_reported_and_not_healed(tmp_path, monkeypatch, capsys):
    """No matching fill means nobody knows what happened to the position. Reporting is the
    honest answer; closing the book on a guessed price is how a track record starts lying."""
    from equity_scout.shortterm_storage import load_book

    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    _held_book(db_path)
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "fetch_fills", lambda ticker, *, after: [])

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    assert "ABWEICHUNG" in capsys.readouterr().err
    book = load_book(db_path, "session")
    assert book is not None and "TSLA" in book.positions


def test_a_broker_lookup_failure_leaves_the_book_untouched(tmp_path, monkeypatch, capsys):
    """The healer runs before every decision of the session. A broker hiccup in it must not
    take the lane down — nor silently look like 'no fill found'."""
    from equity_scout.shortterm_storage import load_book

    db_path = str(tmp_path / "st.db")
    init_shortterm_db(db_path)
    _held_book(db_path)

    def boom(ticker, *, after):
        raise AlpacaBrokerError("GET /v2/orders -> 500: boom")

    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK-test")
    monkeypatch.setattr(runner, "alpaca_fetch_bars", _fake_feed)
    monkeypatch.setattr(runner, "fetch_broker_positions", dict)
    monkeypatch.setattr(runner, "fetch_fills", boom)

    runner.run_session(db_path, now=datetime(2026, 8, 4, 10, 45, tzinfo=NY), feed="alpaca")

    err = capsys.readouterr().err
    assert "ABWEICHUNG" in err and "500" in err
    book = load_book(db_path, "session")
    assert book is not None and "TSLA" in book.positions
