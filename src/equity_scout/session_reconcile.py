"""Broker-vs-book reconciliation for the session lane (2026-08-04).

Since the broker holds the real position, a difference between it and `shortterm.db` is a
fault report, not something to merge away. Pure comparison — the caller decides whether to
log, alert or halt.

Sub-share differences are expected by design: the book sizes fractionally, `bracket_payload`
rounds down to whole shares. Anything at or above one share is a real divergence.
"""
from __future__ import annotations

from dataclasses import dataclass

from equity_scout.alpaca_broker import BrokerPosition
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
