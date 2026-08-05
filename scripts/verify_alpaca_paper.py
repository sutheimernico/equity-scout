"""Throwaway verification of the Alpaca paper stack before any session-lane rewrite.

Checks the four assumptions the "zeitaktuell" design rests on, and FAILS LOUDLY on each
instead of quietly degrading:
  1. paper credentials are valid                    -> GET  paper-api /v2/account
  2. IEX bars are FRESH and, at 1 minute, DENSE     -> GET  data     /v2/stocks/bars
  3. the broker accepts our orders                  -> POST paper-api /v2/orders (type=limit)
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

Orders are OFF by default: pass --place-orders. Both probes are priced 20 % away from the
market so they *cannot fill* even with the market open, and both are cancelled immediately.
No real money is involved (paper endpoint), but an accidental filled probe in a paper book
corrupts a track record just the same, so it stays opt-in.

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

# Single ticker used by the order probes. Liquid enough that a quote always exists.
PROBE_TICKER = "AAPL"


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


def _bid(client: httpx.Client) -> float:
    quote = client.get(
        f"{DATA_BASE}/stocks/quotes/latest", params={"symbols": PROBE_TICKER, "feed": "iex"}
    )
    if quote.status_code != 200:
        raise VerificationFailed(
            f"GET /v2/stocks/quotes/latest -> {quote.status_code}: {quote.text[:200]}"
        )
    bid = ((quote.json().get("quotes") or {}).get(PROBE_TICKER) or {}).get("bp")
    if not bid:
        raise VerificationFailed(f"Kein Bid fuer {PROBE_TICKER} — Preis nicht bestimmbar.")
    return float(bid)


def check_market_order(client: httpx.Client) -> None:
    """Deliberately NOT a market order.

    A market order fills in milliseconds while the market is open, the DELETE that follows
    then 404s on a filled order, and the probe leaves a real position behind — exactly the
    contamination that made the shared paper account a blocker on 2026-08-05. The question
    this check actually needs to answer is "does the broker accept our orders", and a limit
    order far below the market answers it without ever being fillable.
    """
    print("\n[3/4] Order-Annahme (Limit weit unter Markt, nicht fuellbar)")
    limit_price = round(_bid(client) * 0.80, 2)
    print(f"  Limit {limit_price} (20% unter Bid)")
    _place_and_cancel(
        client,
        {"symbol": PROBE_TICKER, "qty": "1", "side": "buy", "type": "limit",
         "limit_price": str(limit_price), "time_in_force": "day"},
        f"Limit buy 1 {PROBE_TICKER}",
    )


def check_stop_order(client: httpx.Client) -> None:
    """The resting stop is what makes an outage survivable — it triggers in the market
    without the machine polling, which is exactly what failed on 2026-07-21.

    A stop *buy* above the market, not a stop sell: selling without a position is a short,
    which a fresh paper account may reject outright and which would leave a short position
    behind if it did not. A buy stop 20 % above the market can only trigger on a move that
    cannot happen before the cancel lands.
    """
    print("\n[4/4] Ruhende Stop-Order")
    stop_price = round(_bid(client) * 1.20, 2)
    print(f"  Stop {stop_price} (20% ueber Bid, kann nicht ausloesen)")
    _place_and_cancel(
        client,
        {"symbol": PROBE_TICKER, "qty": "1", "side": "buy", "type": "stop",
         "stop_price": str(stop_price), "time_in_force": "day"},
        f"Stop buy 1 {PROBE_TICKER}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--place-orders", action="store_true",
        help="Checks 3+4 ausfuehren (platziert und storniert echte Paper-Orders)",
    )
    parser.add_argument(
        "--require-open", action="store_true",
        help="Abbrechen, wenn der US-Markt zu ist (fuer unbeaufsichtigte Laeufe: ohne "
             "offenen Markt ist die Frische ungemessen und ein gruener Lauf waere gelogen)",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    print(f"Alpaca-Paper-Verifikation — {now:%Y-%m-%d %H:%M:%S}Z")
    if args.require_open and not _market_probably_open(now):
        print("\nUEBERSPRUNGEN: US-Markt zu — --require-open verlangt eine offene Session.")
        return 2
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
