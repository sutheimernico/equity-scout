"""Two books that can drift are two books that WILL drift. This compares them and says so
out loud; nothing here merges silently."""
from __future__ import annotations

from dataclasses import replace

from equity_scout.alpaca_broker import BrokerPosition
from equity_scout.session_reconcile import Divergence, reconcile
from equity_scout.shortterm_book import LaneBook, LanePosition


def _book(**positions: LanePosition) -> LaneBook:
    return replace(LaneBook.fresh("session"), positions=dict(positions))


def _pos(qty: float) -> LanePosition:
    return LanePosition(qty=qty, entry_price=300.0, opened_at="2026-08-04T09:45:00-04:00")


def test_matching_books_report_no_divergence() -> None:
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    assert reconcile(_book(AAPL=_pos(3.0)), broker) == []


def test_position_only_at_the_broker_is_reported() -> None:
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    result = reconcile(_book(), broker)
    assert result == [Divergence("AAPL", kind="broker_only", book_qty=0.0, broker_qty=3.0)]


def test_position_only_in_the_book_is_reported() -> None:
    result = reconcile(_book(AAPL=_pos(3.0)), {})
    assert result == [Divergence("AAPL", kind="book_only", book_qty=3.0, broker_qty=0.0)]


def test_quantity_mismatch_is_reported() -> None:
    broker = {"AAPL": BrokerPosition("AAPL", 2.0, 301.0)}
    result = reconcile(_book(AAPL=_pos(3.0)), broker)
    assert result == [Divergence("AAPL", kind="qty_mismatch", book_qty=3.0, broker_qty=2.0)]


def test_rounding_difference_below_one_share_is_not_a_divergence() -> None:
    """The book sizes fractionally, the broker fills whole shares — a sub-share gap is the
    designed consequence of rounding down, not a fault."""
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    assert reconcile(_book(AAPL=_pos(3.9)), broker) == []


def test_a_full_share_gap_is_a_divergence() -> None:
    """Not in the plan: the tolerance boundary itself. Rounding down can lose at most a
    fraction, so a gap of exactly one whole share is never explained by rounding — a book
    of 4.0 should have produced 4 shares, not 3.
    """
    broker = {"AAPL": BrokerPosition("AAPL", 3.0, 301.0)}
    result = reconcile(_book(AAPL=_pos(4.0)), broker)
    assert result == [Divergence("AAPL", kind="qty_mismatch", book_qty=4.0, broker_qty=3.0)]


def test_a_sub_share_book_position_the_broker_never_took_is_not_a_divergence() -> None:
    """bracket_payload refuses anything below one share, so the book can legitimately hold
    a fraction the broker never received. That is the rounding rule working, not drift."""
    assert reconcile(_book(AAPL=_pos(0.4)), {}) == []


def test_divergences_describe_themselves_for_the_log() -> None:
    kinds = {
        "broker_only": Divergence("AAPL", kind="broker_only", book_qty=0.0, broker_qty=3.0),
        "book_only": Divergence("AAPL", kind="book_only", book_qty=3.0, broker_qty=0.0),
        "qty_mismatch": Divergence("AAPL", kind="qty_mismatch", book_qty=3.0, broker_qty=2.0),
    }
    assert "Broker haelt 3" in kinds["broker_only"].describe()
    assert "Buch haelt 3" in kinds["book_only"].describe()
    assert "Buch 3 vs Broker 2" in kinds["qty_mismatch"].describe()


def test_several_tickers_are_reported_in_a_stable_order() -> None:
    """The report goes into a log and a digest line; unstable ordering would make two
    identical states look like two different ones."""
    broker = {"TSLA": BrokerPosition("TSLA", 2.0, 330.0)}
    result = reconcile(_book(NVDA=_pos(5.0), AAPL=_pos(3.0)), broker)
    assert [d.ticker for d in result] == ["AAPL", "NVDA", "TSLA"]
