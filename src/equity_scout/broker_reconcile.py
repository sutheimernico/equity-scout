"""Does the book hold what the venue holds?

The heartbeat SLAs in `watchdog.py` cannot answer this by construction: every chain can run
green while the book and the account drift apart. On 2026-08-19 the ignition lane bought MRVI
three times and booked it once; the difference (296 shares) sat in the paper account for five
days, outside every exit rule, and nothing in the system was looking.

Pure comparison — the caller fetches from the venue and reads the book, this decides. Kept
ignition-only for now (the one lane trading live); generalise when a second lane needs it.
"""
from __future__ import annotations

from equity_scout.alpaca_broker import BrokerPosition

# Alpaca reports fractional quantities as floats; anything below this is representation noise
# rather than an unbooked fill. One thousandth of a share is smaller than any position the
# lanes can open (`ENTRY_FRACTION` of a 10k book buys whole shares of anything above $1).
QTY_TOLERANCE = 1e-3


def divergences(
    book_positions: dict[str, float],
    broker_positions: dict[str, BrokerPosition],
    *,
    owned: set[str] | None = None,
) -> list[dict]:
    """Every ticker where book quantity and broker quantity disagree, sorted by ticker.

    `owned` limits which broker-only tickers count: the paper account is shared with the
    session lane, so a holding this book never claimed is not automatically its problem.
    Defaults to "everything the broker reports", which is what a single-lane account wants.
    """
    tickers = set(book_positions) | {
        t for t in broker_positions if owned is None or t in owned or t in book_positions
    }
    found = []
    for ticker in sorted(tickers):
        book_qty = float(book_positions.get(ticker, 0.0))
        broker = broker_positions.get(ticker)
        broker_qty = float(broker.qty) if broker else 0.0
        if abs(book_qty - broker_qty) <= QTY_TOLERANCE:
            continue
        if book_qty <= QTY_TOLERANCE:
            kind = "broker_only"
        elif broker_qty <= QTY_TOLERANCE:
            kind = "book_only"
        elif broker_qty > book_qty:
            kind = "broker_excess"
        else:
            kind = "book_excess"
        found.append({"ticker": ticker, "book_qty": book_qty, "broker_qty": broker_qty,
                      "kind": kind})
    return found


_KIND_TEXT = {
    "broker_excess": "Konto hält MEHR als das Buch",
    "book_excess": "Buch hält mehr als das Konto",
    "broker_only": "nur im Konto, nicht im Buch",
    "book_only": "nur im Buch, nicht im Konto",
}


def divergence_text(found: list[dict]) -> str:
    """One Telegram-ready message naming both numbers per ticker."""
    lines = ["⚠ Buch und Broker-Konto stimmen nicht überein:"]
    for item in found:
        lines.append(
            f"  {item['ticker']}: Buch {item['book_qty']:g} vs Konto {item['broker_qty']:g}"
            f" — {_KIND_TEXT[item['kind']]}"
        )
    lines.append("Solange das offen ist, misst die Lane ein anderes Depot als das echte.")
    return "\n".join(lines)
