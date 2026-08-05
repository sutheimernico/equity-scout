"""Throwaway verification of the Alpaca paper stack before any session-lane rewrite.

Checks the four assumptions the "zeitaktuell" design rests on, and FAILS LOUDLY on each
instead of quietly degrading:
  1. paper credentials are valid                    -> GET  paper-api /v2/account
  2. IEX bars are FRESH and, at 1 minute, DENSE     -> GET  data     /v2/stocks/bars
  3. market orders are accepted                     -> POST paper-api /v2/orders
  4. resting stop orders are accepted               -> POST paper-api /v2/orders (type=stop)

Check 2 is the one that decides the design, and it asks two separate questions because the
lane uses two resolutions: the opening range is built from coarse 15-minute bars (no
real-time need), while the breakout trigger runs on 1-minute bars (the whole point of
moving off yfinance).

  Freshness — the AGE of the newest bar per ticker. If that is not roughly one bar interval,
  the delay we are removing is still there. Only meaningful while the US market is open
  (15:30-22:00 CEST); outside that window the script says so instead of pretending.

  Density — the share of the last 60 one-minute slots that actually carry a bar. IEX is
  ~2-3 % of US volume, so a mega-cap can print no trade at all in a given minute. A
  1-minute trigger on a feed with holes fires late and at prices nobody quoted. Unlike
  freshness this IS measurable outside market hours (it reads the last session's tail),
  so it is verdicted unconditionally.

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

# Two resolutions, two roles: the opening range needs breadth, the breakout trigger needs
# immediacy. Only the second one decides whether "zeitaktuell" is achievable at all.
RANGE_BAR_MINUTES = 15
TRIGGER_BAR_MINUTES = 1

# A bar can only be complete once its interval has elapsed, so one interval of age is
# expected. Beyond two intervals the feed is delayed, not real-time.
def _fresh_limit(bar_minutes: int) -> timedelta:
    return timedelta(minutes=2 * bar_minutes)


# Minutes inspected for density, and the share of them that must carry a bar. 80 % is the
# line below which a 1-minute trigger is guessing: past one hole in five minutes the
# "current" price is routinely a stale print, which is the very bias this design removes.
COVERAGE_MINUTES = 60
MIN_COVERAGE = 0.80


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


def _fetch_bars(client: httpx.Client, *, bar_minutes: int, now: datetime) -> dict:
    """Newest bars per ticker over a 6h lookback, at the given resolution."""
    response = client.get(
        f"{DATA_BASE}/stocks/bars",
        params={
            "symbols": ",".join(SESSION_TICKERS),
            "timeframe": f"{bar_minutes}Min",
            "start": (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "feed": "iex",  # Basic plan: sip (the API default) would 403
            "limit": 10_000,
            "sort": "desc",
        },
    )
    if response.status_code != 200:
        raise VerificationFailed(
            f"GET /v2/stocks/bars ({bar_minutes}Min) -> "
            f"{response.status_code}: {response.text[:300]}"
        )
    return response.json().get("bars") or {}


def _starts(series: list[dict]) -> list[datetime]:
    return [datetime.fromisoformat(b["t"].replace("Z", "+00:00")) for b in series]


def _regular_session_only(starts: set[datetime]) -> set[datetime]:
    """Drop pre- and after-hours bars (UTC bounds, same rough definition as
    _market_probably_open).

    Measured 2026-08-05: anchoring density on the newest bar of *any* session condemns
    exactly the most liquid tickers — MSFT, AMD, AAPL and SPY were the only four still
    printing after 20:00 UTC, so their 60-minute window fell into the thin after-hours tape
    and scored 20-72 %, while the six that stopped at 19:59 scored 100 %. The lane only ever
    trades the regular session, so that is the only window whose density means anything.
    """
    return {t for t in starts if 13 * 60 + 30 <= t.hour * 60 + t.minute < 20 * 60}


def _coverage(series: list[dict]) -> float:
    """Share of the COVERAGE_MINUTES regular-session slots ending at the newest
    regular-session bar that carry a bar.

    Anchored on that bar rather than on `now`, so the number means the same thing whether
    the market is open or the last session ended hours ago.
    """
    starts = _regular_session_only(set(_starts(series)))
    if not starts:
        return 0.0
    window_start = max(starts) - timedelta(minutes=COVERAGE_MINUTES - 1)
    return sum(1 for t in starts if t >= window_start) / COVERAGE_MINUTES


def _report_resolution(
    bars: dict, *, bar_minutes: int, now: datetime, open_now: bool, label: str
) -> list[str]:
    """Print one line per ticker; return the tickers with no data at all."""
    print(f"\n  {bar_minutes}-Minuten-Bars — {label}")
    limit = _fresh_limit(bar_minutes)
    missing = []
    for ticker in SESSION_TICKERS:
        series = bars.get(ticker)
        if not series:
            print(f"    FEHLT {ticker:5s} keine Bars im 6h-Fenster")
            missing.append(ticker)
            continue
        newest = max(_starts(series))
        age = now - newest
        # Age is only a verdict while the market is open; after the close every bar is
        # legitimately old and flagging that would be noise.
        verdict = "----" if not open_now else ("OK  " if age <= limit else "ALT ")
        line = (f"    {verdict}{ticker:5s} neuester Bar {newest:%H:%M:%S}Z  Alter "
                f"{age.total_seconds() / 60:6.1f} min  ({len(series)} Bars")
        if bar_minutes == TRIGGER_BAR_MINUTES:
            share = _coverage(series)
            flag = "OK" if share >= MIN_COVERAGE else "LUECKENHAFT"
            line += f", Dichte {share:5.0%} {flag}"
        print(line + ")")
    return missing


def check_bar_freshness(client: httpx.Client, *, now: datetime) -> None:
    print("\n[2/4] IEX-Bars (feed=iex) — der entscheidende Test")
    open_now = _market_probably_open(now)

    range_bars = _fetch_bars(client, bar_minutes=RANGE_BAR_MINUTES, now=now)
    missing = _report_resolution(
        range_bars, bar_minutes=RANGE_BAR_MINUTES, now=now, open_now=open_now,
        label="Basis der Opening Range, Frische unkritisch",
    )

    trigger_bars = _fetch_bars(client, bar_minutes=TRIGGER_BAR_MINUTES, now=now)
    missing += _report_resolution(
        trigger_bars, bar_minutes=TRIGGER_BAR_MINUTES, now=now, open_now=open_now,
        label="Basis des Ausbruch-Triggers, hier entscheidet sich alles",
    )

    if missing:
        raise VerificationFailed(
            f"Keine Bars fuer: {', '.join(sorted(set(missing)))} — Universum anpassen "
            "oder Feed pruefen."
        )

    coverage = {t: _coverage(s) for t, s in trigger_bars.items()}
    thin = {t: share for t, share in coverage.items() if share < MIN_COVERAGE}
    if thin:
        detail = ", ".join(f"{t} {share:.0%}" for t, share in sorted(thin.items()))
        raise VerificationFailed(
            f"1-Minuten-Bars sind zu lueckenhaft (unter {MIN_COVERAGE:.0%} der letzten "
            f"{COVERAGE_MINUTES} Minuten): {detail}. Ein Minuten-Trigger auf diesem Feed "
            "handelt auf veralteten Prints — Auswahl verkleinern oder auf eine groebere "
            "Trigger-Aufloesung zurueck."
        )

    if not open_now:
        print("\n  HINWEIS US-Markt ist gerade zu (Regular Session 13:30-20:00 UTC / "
              "15:30-22:00 MESZ).\n           Die DICHTE oben gilt trotzdem (sie liest das "
              "Ende der letzten Session),\n           das ALTER nicht — dafuer muss der "
              "Lauf bei offenem Markt wiederholt werden.")


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
