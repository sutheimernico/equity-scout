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
    for attempt in range(attempts):
        if order.filled_qty and order.filled_avg_price is not None:
            return order
        if order.status in TERMINAL_STATUSES:
            return order
        if attempt:
            sleep(delay)
        order = fetch(order.order_id)
    if order.filled_qty and order.filled_avg_price is not None:
        return order
    try:
        cancel(order.order_id)
    except AlpacaBrokerError:
        return fetch(order.order_id)  # refused = it filled while we were cancelling
    return order


def close_position(ticker: str) -> BrokerOrder:
    """Flatten one position at market and cancel its resting bracket legs (network)."""
    with _client() as client:
        response = client.delete(f"{PAPER_BASE}/positions/{ticker}")
    if response.status_code not in (200, 207):
        raise AlpacaBrokerError(
            f"DELETE /v2/positions/{ticker} -> {response.status_code}: {response.text[:300]}"
        )
    return parse_order(response.json())
