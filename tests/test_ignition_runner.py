"""The two booking defects the live run of 2026-08-19 produced: MRVI was bought three times
(424 shares at the venue) and booked once (128), because the entry path threw away the only
state that knew what had actually filled. Both tests feed the case the old code did NOT
handle — a fill that lands after the poll window, and a partial fill."""
from __future__ import annotations

import scripts.run_ignition_lane as runner
from equity_scout.alpaca_broker import BrokerOrder, BrokerPosition
from equity_scout.shortterm_storage import get_lane_state, init_shortterm_db


def test_a_fill_that_lands_after_the_poll_window_is_booked() -> None:
    """await_fill gives up unfilled; settle_or_cancel's cancel is refused because the order
    completed, and its re-read is the fact. Discarding it left the venue holding a position
    the book never saw — and the next minute bought it again."""
    settled = BrokerOrder(order_id="o1", status="filled", filled_qty=142.0,
                          filled_avg_price=7.01)
    assert runner.bookable(settled) == (142.0, 7.01)


def test_a_partial_fill_books_exactly_what_filled() -> None:
    """settle_or_cancel cancels the resting remainder, so a partial fill is final: book the
    128 that filled, not the 141 that were ordered."""
    settled = BrokerOrder(order_id="o2", status="canceled", filled_qty=128.0,
                          filled_avg_price=7.05)
    assert runner.bookable(settled) == (128.0, 7.05)


def test_nothing_filled_is_no_entry() -> None:
    settled = BrokerOrder(order_id="o3", status="canceled", filled_qty=0.0,
                          filled_avg_price=None)
    assert runner.bookable(settled) is None


def test_a_quantity_without_a_price_is_no_entry() -> None:
    """A fill we cannot price cannot be booked honestly — the book would carry an invented
    entry price and every later return would be measured against it."""
    settled = BrokerOrder(order_id="o4", status="filled", filled_qty=10.0,
                          filled_avg_price=None)
    assert runner.bookable(settled) is None


def test_a_divergence_is_recorded_for_the_watchdog(tmp_path) -> None:
    """The runner talks to the broker anyway; the watchdog is DB-only by design. So the
    runner writes the finding and the watchdog alarms on it — no network in the dead-man."""
    db = str(tmp_path / "st.db")
    init_shortterm_db(db)
    runner.record_divergence(
        db, book_positions={"MRVI": 128.0},
        broker_positions={"MRVI": BrokerPosition("MRVI", 424.0, 7.0)},
        now="2026-08-24T17:00:00+00:00",
    )
    state = get_lane_state(db, runner.LANE, runner.DIVERGENCE_KEY)
    assert state is not None and "424" in state


def test_no_divergence_clears_the_state(tmp_path) -> None:
    """A stale warning is worse than none: it trains you to ignore the channel."""
    db = str(tmp_path / "st.db")
    init_shortterm_db(db)
    runner.record_divergence(
        db, book_positions={"MRVI": 128.0},
        broker_positions={"MRVI": BrokerPosition("MRVI", 424.0, 7.0)},
        now="2026-08-24T17:00:00+00:00",
    )
    runner.record_divergence(
        db, book_positions={"MRVI": 424.0},
        broker_positions={"MRVI": BrokerPosition("MRVI", 424.0, 7.0)},
        now="2026-08-24T17:01:00+00:00",
    )
    assert not get_lane_state(db, runner.LANE, runner.DIVERGENCE_KEY)
