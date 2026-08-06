"""The broker seam. Every test fakes the transport — a live call from the suite would
place orders in the paper book and corrupt the track record it exists to measure."""
from __future__ import annotations

import pytest

from equity_scout.alpaca_broker import (
    AlpacaBrokerError,
    BrokerOrder,
    await_fill,
    BrokerPosition,
    bracket_payload,
    close_position,
    open_order_ids,
    parse_order,
    parse_positions,
    settle_or_cancel,
)


def test_bracket_payload_carries_stop_and_target() -> None:
    payload = bracket_payload("AAPL", qty=3.5, stop_price=295.0, target_price=310.0)
    assert payload["symbol"] == "AAPL"
    assert payload["side"] == "buy"
    assert payload["type"] == "market"
    assert payload["order_class"] == "bracket"
    assert payload["time_in_force"] == "day"
    assert payload["stop_loss"]["stop_price"] == "295.00"
    assert payload["take_profit"]["limit_price"] == "310.00"


def test_bracket_payload_rounds_quantity_down_to_whole_shares() -> None:
    """Bracket orders reject fractional quantities at Alpaca. Rounding DOWN keeps the
    position inside the size the book approved."""
    assert bracket_payload("AAPL", qty=3.9, stop_price=1.0, target_price=2.0)["qty"] == "3"


def test_bracket_payload_rejects_a_position_below_one_share() -> None:
    with pytest.raises(AlpacaBrokerError, match="unter einer ganzen Aktie"):
        bracket_payload("AAPL", qty=0.4, stop_price=1.0, target_price=2.0)


def test_parse_positions_maps_symbol_to_qty_and_price() -> None:
    positions = parse_positions([
        {"symbol": "AAPL", "qty": "3", "avg_entry_price": "301.25"},
        {"symbol": "TSLA", "qty": "2", "avg_entry_price": "330.10"},
    ])
    assert positions["AAPL"] == BrokerPosition(ticker="AAPL", qty=3.0, avg_entry_price=301.25)
    assert len(positions) == 2


def test_parse_order_reports_an_unfilled_order_as_none_price() -> None:
    order = parse_order({"id": "abc", "status": "accepted", "filled_qty": "0",
                         "filled_avg_price": None})
    assert order.order_id == "abc"
    assert order.filled_qty == 0.0
    assert order.filled_avg_price is None


def test_parse_order_reads_a_filled_order() -> None:
    order = parse_order({"id": "abc", "status": "filled", "filled_qty": "3",
                         "filled_avg_price": "301.44"})
    assert order.filled_qty == 3.0
    assert order.filled_avg_price == 301.44


def test_parse_order_keeps_a_zero_fill_price_distinct_from_no_fill() -> None:
    """Not in the plan. "0.0" is a real (if pathological) price and must not silently
    become None — that is the difference between "filled at zero, investigate" and
    "not filled yet, wait", and the reconciliation acts differently on each."""
    order = parse_order({"id": "abc", "status": "filled", "filled_qty": "1",
                         "filled_avg_price": "0.0"})
    assert order.filled_avg_price == 0.0


# --- Reading the fill back (found live 2026-08-06) -----------------------------------------
# Alpaca answers POST /v2/orders with `pending_new`, ALWAYS — the fill arrives milliseconds
# later. The first live run therefore placed four bracket orders, booked none of them, and
# left four positions the book knew nothing about. The fill has to be read back.

def _order(status: str, qty: float = 0.0, price: float | None = None) -> BrokerOrder:
    return BrokerOrder(order_id="o1", status=status, filled_qty=qty, filled_avg_price=price)


def test_a_fill_that_arrives_on_the_second_look_is_returned() -> None:
    answers = [_order("pending_new"), _order("filled", 3.0, 490.72)]
    slept: list[float] = []
    settled = settle_or_cancel(
        _order("pending_new"),
        fetch=lambda _id: answers.pop(0),
        sleep=slept.append,
        cancel=lambda _id: (_ for _ in ()).throw(AssertionError("must not cancel a fill")),
    )
    assert settled.filled_avg_price == 490.72
    assert slept, "it has to wait at least once before giving up"


def test_an_order_that_never_fills_is_cancelled_not_left_resting() -> None:
    """An unbooked resting order is a position nobody manages."""
    cancelled: list[str] = []
    settled = settle_or_cancel(
        _order("pending_new"),
        fetch=lambda _id: _order("new"),
        sleep=lambda _s: None,
        cancel=cancelled.append,
        attempts=2,
    )
    assert cancelled == ["o1"]
    assert settled.filled_avg_price is None


def test_a_fill_that_wins_the_race_against_the_cancel_is_still_booked() -> None:
    """Cancel refused means it filled in the meantime — read it back rather than lose it."""
    reads = [_order("new"), _order("new"), _order("filled", 2.0, 717.64)]

    def refuse(_id: str) -> None:
        raise AlpacaBrokerError("order already filled")

    settled = settle_or_cancel(
        _order("pending_new"),
        fetch=lambda _id: reads.pop(0),
        sleep=lambda _s: None,
        cancel=refuse,
        attempts=2,
    )
    assert settled.filled_avg_price == 717.64


def test_a_rejected_order_stops_the_polling_at_once() -> None:
    looks: list[str] = []

    def fetch(order_id: str) -> BrokerOrder:
        looks.append(order_id)
        return _order("rejected")

    settled = settle_or_cancel(
        _order("pending_new"), fetch=fetch, sleep=lambda _s: None,
        cancel=lambda _id: (_ for _ in ()).throw(AssertionError("nothing to cancel")),
        attempts=5,
    )
    assert settled.status == "rejected"
    assert len(looks) == 1, "a terminal status must not be polled again"


# --- Exits must cancel the resting legs first (found live 2026-08-06) ----------------------

def test_open_order_ids_reads_the_ids_of_a_symbols_resting_orders() -> None:
    rows = [{"id": "a", "symbol": "TSLA"}, {"id": "b", "symbol": "TSLA"}]
    assert open_order_ids(rows) == ["a", "b"]


def test_closing_cancels_the_resting_legs_before_flattening() -> None:
    """Alpaca answers DELETE /v2/positions/TSLA with 403 `held_for_orders` while the bracket's
    take-profit leg still holds the shares. Without cancelling first EVERY exit of the lane
    failed — and the fallback booked the book flat while the broker kept the position.
    """
    calls: list[str] = []

    def fake_cancel(ticker: str) -> None:
        calls.append(f"cancel:{ticker}")

    def fake_flatten(ticker: str) -> BrokerOrder:
        calls.append(f"flatten:{ticker}")
        return _order("filled", 4.0, 321.5)

    order = close_position("TSLA", cancel_open=fake_cancel, flatten=fake_flatten)
    assert calls == ["cancel:TSLA", "flatten:TSLA"]
    assert order.filled_avg_price == 321.5


def test_await_fill_waits_without_ever_cancelling() -> None:
    """An exit must go through: a flatten that is cancelled leaves the position open. So the
    exit path polls but never cancels — unlike an entry, which may be abandoned."""
    answers = [_order("pending_new"), _order("filled", 4.0, 321.5)]
    order = await_fill(_order("pending_new"), fetch=lambda _id: answers.pop(0),
                       sleep=lambda _s: None)
    assert order.filled_avg_price == 321.5


def test_await_fill_gives_up_after_its_attempts_without_pretending() -> None:
    order = await_fill(_order("pending_new"), fetch=lambda _id: _order("new"),
                       sleep=lambda _s: None, attempts=2)
    assert order.filled_avg_price is None and order.status == "new"
