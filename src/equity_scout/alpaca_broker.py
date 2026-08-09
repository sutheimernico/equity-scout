"""Alpaca PAPER broker seam for the session lane (2026-08-04).

LOOP.md permits order routing to a paper account since 2026-08-04 and forbids real money
unconditionally. This module therefore hardcodes the paper host: there is no configuration
switch that could point it at a live endpoint, because a configurable one would eventually
be misconfigured.

Entries go out as BRACKET orders — entry, stop-loss and take-profit in one instruction — so
the position is protected in the market itself. That is the point: on 2026-07-21 the machine
stopped running for two days with five positions open, and no local stop can fire when the
process that would check it is not alive.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

DATA_BASE = "https://data.alpaca.markets/v2"
PAPER_BASE = "https://paper-api.alpaca.markets/v2"  # never parameterised — see docstring


# How long a freshly placed order is given to report its fill before it is cancelled. A
# market bracket on a mega-cap fills in well under a second on the paper venue; this only has
# to outlast the round trip, and the caller runs on a one-minute cron.
FILL_POLL_ATTEMPTS = 6
FILL_POLL_SECONDS = 0.4

# Statuses an order never leaves — polling them again only costs time.
TERMINAL_STATUSES = frozenset({"canceled", "cancelled", "expired", "rejected", "done_for_day"})


class AlpacaBrokerError(RuntimeError):
    """An order or account call did not do what the caller assumed."""


@dataclass(frozen=True)
class BrokerPosition:
    ticker: str
    qty: float
    avg_entry_price: float


@dataclass(frozen=True)
class BrokerOrder:
    order_id: str
    status: str
    filled_qty: float
    filled_avg_price: float | None  # None until something actually filled


@dataclass(frozen=True)
class BrokerFill:
    """One execution that actually happened at the venue.

    Distinct from `BrokerOrder` because it carries the two fields only a COMPLETED trade has:
    a fill time and a side. The bracket legs fill without us (that is their whole point — see
    the module docstring), so the fill time is what tells the book which of its positions the
    trade belongs to.
    """
    order_id: str
    ticker: str
    side: str
    qty: float
    price: float
    at: str  # ISO timestamp as the venue reported it (UTC)
    # What the resting leg asked for — a stop's stop price, a target's limit price. None for
    # a market order, which asked for no price and therefore has no slippage to measure.
    requested_price: float | None = None


def auth_headers() -> dict[str, str]:
    key, secret = os.getenv("ALPACA_API_KEY_ID"), os.getenv("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        raise AlpacaBrokerError(
            "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY fehlen — Paper-Keys in .env eintragen. "
            "Dieses Repo hat kein python-dotenv: die Shell muss .env sourcen "
            "(set -a && . ./.env && set +a)."
        )
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def bracket_payload(ticker: str, *, qty: float, stop_price: float, target_price: float) -> dict:
    """Market entry with a resting stop and target. Quantity is rounded DOWN to whole
    shares: Alpaca rejects fractional quantities for bracket orders, and rounding up would
    take more risk than the book sized for."""
    whole = int(qty)
    if whole < 1:
        raise AlpacaBrokerError(
            f"{ticker}: Position {qty:.4f} liegt unter einer ganzen Aktie — "
            "Bracket-Order nicht moeglich."
        )
    return {
        "symbol": ticker,
        "qty": str(whole),
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "order_class": "bracket",
        "stop_loss": {"stop_price": f"{stop_price:.2f}"},
        "take_profit": {"limit_price": f"{target_price:.2f}"},
    }


def parse_positions(rows: list[dict]) -> dict[str, BrokerPosition]:
    return {
        row["symbol"]: BrokerPosition(
            ticker=row["symbol"],
            qty=float(row["qty"]),
            avg_entry_price=float(row["avg_entry_price"]),
        )
        for row in rows
    }


def parse_order(row: dict) -> BrokerOrder:
    # Absence, not falsiness: a numeric 0 or the string "0.0" is a real price the
    # reconciliation must see, while None means "nothing filled yet". Collapsing both to
    # None would turn a broker anomaly into an ordinary pending order.
    price = row.get("filled_avg_price")
    return BrokerOrder(
        order_id=row["id"],
        status=row["status"],
        filled_qty=float(row.get("filled_qty") or 0.0),
        filled_avg_price=float(price) if price not in (None, "") else None,
    )


def _leg_price(row: dict) -> float | None:
    """What this order asked for: a stop leg its stop price, a target leg its limit price."""
    for key in ("stop_price", "limit_price"):
        value = row.get(key)
        if value not in (None, ""):
            return float(value)
    return None


def parse_fills(rows: list[dict]) -> list[BrokerFill]:
    """Every row of an /v2/orders listing that actually traded, oldest fill first.

    A bracket submits three orders and at most two of them ever fill; the rest are cancelled
    by the OCO link. Only a row with a fill price AND a fill time is an execution — a fill
    without a timestamp cannot be placed in time, and matching it to a position would be a
    guess (see `session_reconcile.resolve_book_only`).
    """
    fills = [
        BrokerFill(
            order_id=row["id"],
            ticker=row["symbol"],
            side=row["side"],
            qty=float(row.get("filled_qty") or 0.0),
            price=float(row["filled_avg_price"]),
            at=row["filled_at"],
            requested_price=_leg_price(row),
        )
        for row in rows
        if row.get("status") == "filled"
        and row.get("filled_avg_price") not in (None, "")
        and row.get("filled_at")
    ]
    return sorted(fills, key=lambda fill: fill.at)


def _client():  # noqa: ANN202 - httpx.Client, lazily imported to keep tests offline
    import httpx

    return httpx.Client(headers=auth_headers(), timeout=30.0)


def fetch_positions() -> dict[str, BrokerPosition]:
    """Every open position in the paper account (network)."""
    with _client() as client:
        response = client.get(f"{PAPER_BASE}/positions")
    if response.status_code != 200:
        raise AlpacaBrokerError(
            f"GET /v2/positions -> {response.status_code}: {response.text[:300]}"
        )
    return parse_positions(response.json())


def fetch_fills(ticker: str, *, after: str) -> list[BrokerFill]:
    """Executions of one symbol since `after` (network).

    `after` is passed to the venue rather than filtered here: the account's order history
    grows without bound, and the caller only ever asks about a position opened today.
    """
    with _client() as client:
        response = client.get(
            f"{PAPER_BASE}/orders",
            params={"status": "closed", "symbols": ticker, "after": after,
                    "limit": 100, "direction": "asc"},
        )
    if response.status_code != 200:
        raise AlpacaBrokerError(
            f"GET /v2/orders ({ticker}) -> {response.status_code}: {response.text[:300]}"
        )
    return parse_fills(response.json())


def place_bracket(ticker: str, *, qty: float, stop_price: float,
                  target_price: float) -> BrokerOrder:
    """Submit a bracket entry (network). Raises on rejection — a swallowed rejection would
    leave the book believing it holds something it does not."""
    payload = bracket_payload(ticker, qty=qty, stop_price=stop_price, target_price=target_price)
    with _client() as client:
        response = client.post(f"{PAPER_BASE}/orders", json=payload)
    if response.status_code not in (200, 201):
        raise AlpacaBrokerError(
            f"POST /v2/orders ({ticker}) -> {response.status_code}: {response.text[:300]}"
        )
    return parse_order(response.json())


def fetch_order(order_id: str) -> BrokerOrder:
    """One order's current state (network)."""
    with _client() as client:
        response = client.get(f"{PAPER_BASE}/orders/{order_id}")
    if response.status_code != 200:
        raise AlpacaBrokerError(
            f"GET /v2/orders/{order_id} -> {response.status_code}: {response.text[:300]}"
        )
    return parse_order(response.json())


def cancel_order(order_id: str) -> None:
    """Cancel one order (network). Raises when the venue refuses — which, for an order that
    filled a moment ago, is the normal answer and tells the caller to read it back."""
    with _client() as client:
        response = client.delete(f"{PAPER_BASE}/orders/{order_id}")
    if response.status_code not in (200, 204):
        raise AlpacaBrokerError(
            f"DELETE /v2/orders/{order_id} -> {response.status_code}: {response.text[:300]}"
        )


def await_fill(
    order: BrokerOrder,
    *,
    fetch: Callable[[str], BrokerOrder] = fetch_order,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = FILL_POLL_ATTEMPTS,
    delay: float = FILL_POLL_SECONDS,
) -> BrokerOrder:
    """Read an order back until it has filled or reached a terminal status. NEVER cancels.

    Used for exits: a flatten that gets cancelled leaves the position open, whereas an entry
    may be abandoned (see settle_or_cancel). Both DELETE /v2/positions and POST /v2/orders
    answer `pending_new` before the fill lands, so the price has to be read back — booking the
    signal price instead made the cleanup of 2026-08-06 record five exits at their entry price.
    """
    for attempt in range(attempts):
        # FULLY filled, not "something filled": MSFT filled 1 of 2 shares first on 2026-08-06
        # and the caller booked 1 while the broker went on to hold 2.
        if order.status == "filled" and order.filled_avg_price is not None:
            return order
        if order.status in TERMINAL_STATUSES:
            return order
        if attempt:
            sleep(delay)
        order = fetch(order.order_id)
    return order


def settle_or_cancel(
    order: BrokerOrder,
    *,
    fetch: Callable[[str], BrokerOrder] = fetch_order,
    sleep: Callable[[float], None] = time.sleep,
    cancel: Callable[[str], None] = cancel_order,
    attempts: int = FILL_POLL_ATTEMPTS,
    delay: float = FILL_POLL_SECONDS,
) -> BrokerOrder:
    """Read a freshly placed order back until it has filled — and cancel it if it has not.

    Alpaca answers POST /v2/orders with `pending_new` even for a market bracket that fills
    milliseconds later, so a caller that trusts the POST response books nothing. The first
    live run (2026-08-06) placed four brackets that way and left four positions the book knew
    nothing about — unmanaged by design, because the book cannot manage what it never saw.

    Cancelling on timeout is the other half of that rule: an order resting at the venue that
    the book has not booked is exactly the same problem, one minute later. If the cancel is
    refused the order filled in the meantime, so it is read back once more and returned.
    """
    order = await_fill(order, fetch=fetch, sleep=sleep, attempts=attempts, delay=delay)
    if order.status == "filled" or order.status in TERMINAL_STATUSES:
        return order  # nothing left pending — a rejection has nothing to cancel either
    try:
        cancel(order.order_id)
    except AlpacaBrokerError:
        pass  # refused = it completed while we were cancelling
    # The FINAL state after the cancel: whatever actually filled and nothing still pending, so
    # the book and the broker end up holding the same quantity even after a partial fill.
    return fetch(order.order_id)


def open_order_ids(rows: list[dict]) -> list[str]:
    """Order ids from an /v2/orders listing."""
    return [row["id"] for row in rows]


def cancel_open_orders(ticker: str) -> None:
    """Cancel every resting order of one symbol (network), best effort.

    An order that finished between listing and cancelling answers 422 — that is the desired
    end state, so it is not an error here.
    """
    with _client() as client:
        listing = client.get(
            f"{PAPER_BASE}/orders", params={"status": "open", "symbols": ticker, "limit": 100}
        )
        if listing.status_code != 200:
            raise AlpacaBrokerError(
                f"GET /v2/orders ({ticker}) -> {listing.status_code}: {listing.text[:200]}"
            )
        for order_id in open_order_ids(listing.json()):
            client.delete(f"{PAPER_BASE}/orders/{order_id}")


def _flatten(ticker: str) -> BrokerOrder:
    with _client() as client:
        response = client.delete(f"{PAPER_BASE}/positions/{ticker}")
    if response.status_code not in (200, 207):
        raise AlpacaBrokerError(
            f"DELETE /v2/positions/{ticker} -> {response.status_code}: {response.text[:300]}"
        )
    return parse_order(response.json())


def close_position(
    ticker: str,
    *,
    cancel_open: Callable[[str], None] = cancel_open_orders,
    flatten: Callable[[str], BrokerOrder] = _flatten,
) -> BrokerOrder:
    """Flatten one position at market — cancelling its resting bracket legs FIRST.

    Alpaca does not release the shares a resting take-profit leg holds: the flatten answers
    `403 insufficient qty available for order … held_for_orders: 4`. Measured live on
    2026-08-06, and it made every exit of the session lane fail — whereupon the caller's
    fallback booked the book flat while the broker still held the position, which is the exact
    divergence the broker-is-truth design exists to prevent.
    """
    cancel_open(ticker)
    return flatten(ticker)
