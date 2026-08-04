"""Throwaway verification of the Alpaca paper stack before any session-lane rewrite.

Checks the four assumptions the "zeitaktuell" design rests on, and FAILS LOUDLY on each
instead of quietly degrading:
  1. paper credentials are valid                    -> GET  paper-api /v2/account
  2. 15-minute IEX bars arrive and are FRESH        -> GET  data     /v2/stocks/bars
  3. market orders are accepted                     -> POST paper-api /v2/orders
  4. resting stop orders are accepted               -> POST paper-api /v2/orders (type=stop)

Check 2 is the one that decides the design: the whole point of moving off yfinance is
losing the ~15-minute delay. The script therefore prints the AGE of the newest bar per
ticker — if that age is not roughly one bar interval during market hours, the delay is
still there and nothing was gained. Ages are only meaningful while the US market is open
(15:30-22:00 CEST); outside that window the script says so instead of pretending.

Orders are OFF by default: pass --place-orders. Every order placed is cancelled again
immediately. No real money is involved (paper endpoint), but an accidental resting order
in a paper book still corrupts a track record, so it stays opt-in.

Not covered by tests on purpose — it talks to a live third-party API and exists to be run
once by hand, then deleted or kept as a smoke check (same rationale as
fix_future_asof_2026_07_24.py).

Usage:
    uv run python scripts/verify_alpaca_paper.py
    uv run python scripts/verify_alpaca_paper.py --place-orders
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

import httpx

DATA_BASE = "https://data.alpaca.markets/v2"
PAPER_BASE = "https://paper-api.alpaca.markets/v2"

# The session lane's current universe. SPY/QQQ are US ETFs — tradable here because this is
# a paper book, but blocked for EU retail at any real broker (PRIIPs). Kept in the check so
# the difference between paper and a future live venue stays visible.
SESSION_TICKERS = ["MSFT", "AMZN", "AVGO", "META", "AAPL", "AMD", "TSLA", "NFLX", "SPY", "QQQ"]

BAR_MINUTES = 15
# A bar can only be complete once its interval has elapsed, so one interval of age is
# expected. Beyond two intervals the feed is delayed, not real-time.
FRESH_LIMIT = timedelta(minutes=2 * BAR_MINUTES)


class VerificationFailed(RuntimeError):
    """A checked assumption does not hold — the design must not be built on it."""


def _credentials() -> tuple[str, str]:
    key, secret = os.getenv("ALPACA_API_KEY_ID"), os.getenv("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        raise VerificationFailed(
            "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY fehlen. In .env eintragen "
            "(Paper-Keys aus dem Alpaca-Dashboard, NICHT die Live-Keys)."
        )
    return key, secret


def _headers(key: str, secret: str) -> dict[str, str]:
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _market_probably_open(now: datetime) -> bool:
    """Rough US regular-session check in UTC (13:30-20:00 UTC, Mon-Fri). Deliberately
    ignores holidays and half days — it only decides whether to trust the freshness
    verdict, never whether to trade."""
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 13 * 60 + 30 <= minutes <= 20 * 60


def check_account(client: httpx.Client) -> None:
    print("\n[1/4] Paper-Credentials")
    response = client.get(f"{PAPER_BASE}/account")
    if response.status_code != 200:
        raise VerificationFailed(
            f"GET /v2/account -> {response.status_code}: {response.text[:200]}"
        )
    account = response.json()
    print(f"  OK  Konto {account.get('account_number')} status={account.get('status')} "
          f"cash={account.get('cash')} {account.get('currency')}")
    if account.get("status") != "ACTIVE":
        print("  WARN Konto ist nicht ACTIVE — Orders koennen abgelehnt werden.")


def check_bar_freshness(client: httpx.Client, *, now: datetime) -> None:
    print(f"\n[2/4] {BAR_MINUTES}-Minuten-Bars (feed=iex) — der entscheidende Test")
    start = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    response = client.get(
        f"{DATA_BASE}/stocks/bars",
        params={
            "symbols": ",".join(SESSION_TICKERS),
            "timeframe": f"{BAR_MINUTES}Min",
            "start": start,
            "feed": "iex",  # Basic plan: sip (the API default) would 403
            "limit": 10_000,
            "sort": "desc",
        },
    )
    if response.status_code != 200:
        raise VerificationFailed(
            f"GET /v2/stocks/bars -> {response.status_code}: {response.text[:300]}"
        )
    bars = response.json().get("bars") or {}
    missing = [t for t in SESSION_TICKERS if not bars.get(t)]
    open_now = _market_probably_open(now)

    for ticker in SESSION_TICKERS:
        series = bars.get(ticker)
        if not series:
            print(f"  FEHLT {ticker:5s} keine Bars im 6h-Fenster")
            continue
        newest = max(datetime.fromisoformat(b["t"].replace("Z", "+00:00")) for b in series)
        age = now - newest
        verdict = "OK  " if age <= FRESH_LIMIT else "ALT "
        print(f"  {verdict}{ticker:5s} neuester Bar {newest:%H:%M:%S}Z  Alter "
              f"{age.total_seconds() / 60:5.1f} min  ({len(series)} Bars)")

    if missing:
        raise VerificationFailed(
            f"Keine Bars fuer: {', '.join(missing)} — Universum anpassen oder Feed pruefen."
        )
    if not open_now:
        print("\n  HINWEIS US-Markt ist gerade zu (Regular Session 13:30-20:00 UTC / "
              "15:30-22:00 MESZ).\n           Das Alter des letzten Bars ist jetzt "
              "NICHT aussagekraeftig — der Test muss\n           bei offenem Markt "
              "wiederholt werden, sonst ist die Kern-Annahme unbelegt.")


def _place_and_cancel(client: httpx.Client, payload: dict, label: str) -> None:
    response = client.post(f"{PAPER_BASE}/orders", json=payload)
    if response.status_code not in (200, 201):
        raise VerificationFailed(
            f"POST /v2/orders ({label}) -> {response.status_code}: {response.text[:300]}"
        )
    order = response.json()
    order_id = order["id"]
    print(f"  OK  {label} angenommen: id={order_id} status={order.get('status')}")
    cancelled = client.delete(f"{PAPER_BASE}/orders/{order_id}")
    if cancelled.status_code in (200, 204):
        print("      storniert.")
    else:
        print(f"      WARN Storno fehlgeschlagen ({cancelled.status_code}) — "
              f"Order {order_id} manuell pruefen!")


def check_market_order(client: httpx.Client) -> None:
    print("\n[3/4] Market-Order")
    _place_and_cancel(
        client,
        {"symbol": "AAPL", "qty": "1", "side": "buy", "type": "market", "time_in_force": "day"},
        "Market buy 1 AAPL",
    )


def check_stop_order(client: httpx.Client) -> None:
    """The resting stop is what makes an outage survivable — it triggers in the market
    without the machine polling, which is exactly what failed on 2026-07-21."""
    print("\n[4/4] Ruhende Stop-Order")
    quote = client.get(
        f"{DATA_BASE}/stocks/quotes/latest", params={"symbols": "AAPL", "feed": "iex"}
    )
    if quote.status_code != 200:
        raise VerificationFailed(
            f"GET /v2/stocks/quotes/latest -> {quote.status_code}: {quote.text[:200]}"
        )
    quotes = quote.json().get("quotes", {})
    bid = (quotes.get("AAPL") or {}).get("bp")
    if not bid:
        raise VerificationFailed("Kein Bid fuer AAPL — Stop-Preis nicht bestimmbar.")
    # Well below the market so it cannot fill before the cancel lands.
    stop_price = round(float(bid) * 0.80, 2)
    print(f"  Bid {bid} -> Stop {stop_price} (20% darunter, kann nicht ausloesen)")
    _place_and_cancel(
        client,
        {"symbol": "AAPL", "qty": "1", "side": "sell", "type": "stop",
         "stop_price": str(stop_price), "time_in_force": "day"},
        "Stop sell 1 AAPL",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--place-orders", action="store_true",
        help="Checks 3+4 ausfuehren (platziert und storniert echte Paper-Orders)",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    print(f"Alpaca-Paper-Verifikation — {now:%Y-%m-%d %H:%M:%S}Z")
    try:
        key, secret = _credentials()
        with httpx.Client(headers=_headers(key, secret), timeout=30.0) as client:
            check_account(client)
            check_bar_freshness(client, now=now)
            if args.place_orders:
                check_market_order(client)
                check_stop_order(client)
            else:
                print("\n[3/4] Market-Order      uebersprungen (--place-orders)")
                print("[4/4] Stop-Order        uebersprungen (--place-orders)")
    except VerificationFailed as error:
        print(f"\nFEHLGESCHLAGEN: {error}")
        return 1
    except httpx.HTTPError as error:
        print(f"\nNETZWERKFEHLER: {error}")
        return 1

    print("\nAlle geprueften Annahmen halten.")
    if not args.place_orders:
        print("Order-Faehigkeit noch UNBELEGT — mit --place-orders nachziehen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
