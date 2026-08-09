"""Broker-vs-book reconciliation for the session lane (2026-08-04).

Since the broker holds the real position, a difference between it and `shortterm.db` is a
fault report, not something to merge away. Pure comparison — the caller decides whether to
log, alert or halt.

Sub-share differences are expected by design: the book sizes fractionally, `bracket_payload`
rounds down to whole shares. Anything at or above one share is a real divergence.

One divergence CAN be resolved without guessing, and `resolve_book_only` does it: when the
book still holds what the broker no longer has, the bracket's stop or target leg filled in
the market on its own. That fill is a fact sitting in the order history — reading it back is
not merging the two books, it is booking the trade that happened. Measured on 2026-08-07:
all six stop exits of the day left the book closing itself at the SIGNAL price, on average
0.02% better than the market gave — a bias that only ever points one way.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from equity_scout.alpaca_broker import BrokerFill, BrokerPosition
from equity_scout.shortterm_book import LaneBook

TOLERANCE_SHARES = 1.0


@dataclass(frozen=True)
class Divergence:
    ticker: str
    kind: str  # "broker_only" | "book_only" | "qty_mismatch"
    book_qty: float
    broker_qty: float

    def describe(self) -> str:
        if self.kind == "broker_only":
            return f"{self.ticker}: Broker haelt {self.broker_qty:g}, Buch nichts"
        if self.kind == "book_only":
            return f"{self.ticker}: Buch haelt {self.book_qty:g}, Broker nichts"
        return (
            f"{self.ticker}: Buch {self.book_qty:g} vs Broker {self.broker_qty:g}"
        )


@dataclass(frozen=True)
class BrokerExit:
    """The exit the broker made while nobody was looking, ready to be booked."""
    ticker: str
    qty: float
    price: float  # quantity-weighted across the fills that make up the exit
    at: str
    order_ids: tuple[str, ...]
    # The single price the legs asked for, or None when they did not agree on one. An average
    # of two different expectations would be an expectation nobody ever had.
    requested_price: float | None = None


def _instant(stamp: str) -> datetime | None:
    """An aware timestamp, or None when it cannot be compared.

    The book stamps New York time and Alpaca answers UTC, so these are only ever comparable
    as instants. A naive stamp is refused rather than assumed: read as UTC, a 15:45-04:00
    entry and an 18:00Z fill swap order, and the healer would close today's position with a
    trade that happened four hours before it opened.
    """
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def resolve_book_only(
    divergence: Divergence,
    fills: Sequence[BrokerFill],
    *,
    opened_at: str,
) -> BrokerExit | None:
    """The broker's own exit for a position the book still holds — or None.

    None means "keep reporting, heal nothing". That is the answer for every case where the
    fills do not add up to the position: half an exit booked as a whole one would flatten a
    book position the broker only partly closed, which is the divergence this module exists
    to catch, one step further along.

    Only `book_only` is resolvable. `broker_only` is a position the book never saw — there is
    no fill of ours to book and adopting it would be guessing. `qty_mismatch` means the broker
    still holds part of it, so the position is not closed at all.
    """
    if divergence.kind != "book_only":
        return None
    opened = _instant(opened_at)
    if opened is None:
        return None

    taken: list[BrokerFill] = []
    filled = 0.0
    for fill in fills:
        if fill.ticker != divergence.ticker or fill.side != "sell":
            continue
        at = _instant(fill.at)
        if at is None or at < opened:
            continue
        taken.append(fill)
        filled += fill.qty
        if filled >= divergence.book_qty:
            break
    if not taken or filled < divergence.book_qty - TOLERANCE_SHARES:
        return None

    value = sum(fill.qty * fill.price for fill in taken)
    requested = {fill.requested_price for fill in taken}
    return BrokerExit(
        ticker=divergence.ticker,
        qty=filled,
        price=value / filled,
        at=taken[-1].at,  # when the book actually went flat
        order_ids=tuple(fill.order_id for fill in taken),
        requested_price=requested.pop() if len(requested) == 1 else None,
    )


def reconcile(book: LaneBook, broker: dict[str, BrokerPosition]) -> list[Divergence]:
    """Every ticker where the two books disagree by a share or more.

    Sorted by ticker: the result is rendered into a log line and a digest, where an
    unstable order would make one unchanged state read as a new one on every run.
    """
    out: list[Divergence] = []
    for ticker in sorted({*book.positions, *broker}):
        book_qty = book.positions[ticker].qty if ticker in book.positions else 0.0
        broker_qty = broker[ticker].qty if ticker in broker else 0.0
        if abs(book_qty - broker_qty) < TOLERANCE_SHARES:
            continue
        if broker_qty and not book_qty:
            kind = "broker_only"
        elif book_qty and not broker_qty:
            kind = "book_only"
        else:
            kind = "qty_mismatch"
        out.append(Divergence(ticker, kind=kind, book_qty=book_qty, broker_qty=broker_qty))
    return out
