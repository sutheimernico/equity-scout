"""What the watchdog was structurally unable to see until 2026-08-24: the book and the venue
holding different numbers of the same share."""
from __future__ import annotations

from equity_scout.alpaca_broker import BrokerPosition
from equity_scout.broker_reconcile import divergence_text, divergences


def _pos(ticker: str, qty: float) -> BrokerPosition:
    return BrokerPosition(ticker=ticker, qty=qty, avg_entry_price=7.0)


def test_matching_quantities_are_no_divergence() -> None:
    assert divergences({"MRVI": 128.0}, {"MRVI": _pos("MRVI", 128.0)}) == []


def test_the_live_case_the_broker_holds_more_than_the_book() -> None:
    found = divergences({"MRVI": 128.0}, {"MRVI": _pos("MRVI", 424.0)})
    assert found == [{"ticker": "MRVI", "book_qty": 128.0, "broker_qty": 424.0,
                      "kind": "broker_excess"}]


def test_a_position_the_book_has_and_the_broker_does_not() -> None:
    """The book believing in a position that no longer exists is the mirror failure: every
    exit rule fires against a holding that cannot be sold."""
    found = divergences({"PURR": 110.0}, {})
    assert found == [{"ticker": "PURR", "book_qty": 110.0, "broker_qty": 0.0,
                      "kind": "book_only"}]


def test_a_position_only_the_broker_has() -> None:
    found = divergences({}, {"ELMT": _pos("ELMT", 49.0)})
    assert found == [{"ticker": "ELMT", "book_qty": 0.0, "broker_qty": 49.0,
                      "kind": "broker_only"}]


def test_the_book_holding_more_than_the_account_is_its_own_kind() -> None:
    found = divergences({"MRVI": 424.0}, {"MRVI": _pos("MRVI", 128.0)})
    assert found == [{"ticker": "MRVI", "book_qty": 424.0, "broker_qty": 128.0,
                      "kind": "book_excess"}]


def test_fractional_rounding_is_not_a_divergence() -> None:
    """Alpaca reports fractional quantities; a 1e-9 difference is float noise, not a fill."""
    assert divergences({"SPY": 1.0}, {"SPY": _pos("SPY", 1.0000000001)}) == []


def test_tickers_the_lane_does_not_own_are_ignored() -> None:
    """The paper account is shared with the session lane. Only what this book claims — or
    holds an excess of — is this book's business."""
    assert divergences({}, {"AAPL": _pos("AAPL", 4.0)}, owned={"MRVI"}) == []


def test_an_owned_ticker_is_still_reported_when_only_the_broker_has_it() -> None:
    """The whole live defect: the lane's own ticker in the account and not in the book."""
    found = divergences({}, {"MRVI": _pos("MRVI", 424.0)}, owned={"MRVI"})
    assert found == [{"ticker": "MRVI", "book_qty": 0.0, "broker_qty": 424.0,
                      "kind": "broker_only"}]


def test_findings_are_sorted_by_ticker() -> None:
    found = divergences({"ZM": 1.0, "AMD": 2.0}, {})
    assert [f["ticker"] for f in found] == ["AMD", "ZM"]


def test_the_text_names_both_numbers() -> None:
    text = divergence_text([{"ticker": "MRVI", "book_qty": 128.0, "broker_qty": 424.0,
                             "kind": "broker_excess"}])
    assert "MRVI" in text and "128" in text and "424" in text
