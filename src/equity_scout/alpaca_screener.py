"""Market-WIDE data for the catalyst radar (v16, 2026-08-19).

Why a new module next to alpaca_data.py: that one serves the session lane's fixed
12-ticker universe with IEX bars. The radar has the opposite shape — it must not carry a
ticker list at all, because a list is exactly what made the system blind to Moderna on
2026-08-19 (it sat at scout rank 1852 and in none of our three scope sets).

The screener endpoints solve that in one call each, and they carry a property the bar feed
does not: they are computed on SIP data (all venues), verified live on 2026-08-19 while
/v2/stocks/bars still answers 403 for sip on this plan. So the radar SEES the whole market
even though it can only measure a candidate on the thin IEX feed afterwards.

That asymmetry is also the module's main hazard. The screener's own percent_change is
NOT trustworthy: FIXX was reported at +1378 % on 2026-08-19 while its bars said +7 %,
because the endpoint had divided by a stale close (its last minute bar was from
2024-03-25). Every claim from here therefore has to survive an independent bar check —
which is why fetch_snapshots exists and why callers are expected to use it.

Network code lives in the fetch_* functions and is faked in tests; the parse_* functions
are pure.
"""
from __future__ import annotations

import time as _time
from typing import Any

from equity_scout.alpaca_broker import DATA_BASE, PAPER_BASE, auth_headers

SCREENER_BASE = "https://data.alpaca.markets/v1beta1/screener"
FEED = "iex"  # for the per-symbol verification calls; the screener itself is SIP-based

# Both screener endpoints cap at 100; 50 each keeps one call per side and still reaches far
# past the interesting range (on 2026-08-19 the 50th gainer was +18 %).
SCREENER_TOP = 50

# 200 req/min on the Alpaca free plan. Snapshots take many symbols per call, so a scan
# needs a handful of requests, not hundreds — but a retry storm would still blow through it.
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_SECONDS = 2.0

SNAPSHOT_CHUNK = 200  # symbols per snapshot/quote call; keeps the URL well inside limits


class AlpacaScreenerError(RuntimeError):
    """A market-wide endpoint broke the contract the radar relies on."""


def _get(url: str, params: dict[str, Any]) -> dict:
    """GET with 429-aware retry.

    alpaca_data/alpaca_broker have no backoff because they issue one or two calls per
    minute against a fixed universe. The radar issues more and must not lose a whole scan
    to a single throttle — a silently skipped scan looks exactly like a quiet market.
    """
    import httpx

    last_error = ""
    for attempt in range(RATE_LIMIT_RETRIES):
        with httpx.Client(headers=auth_headers(), timeout=30.0) as client:
            response = client.get(url, params=params)
        if response.status_code == 200:
            return response.json()
        last_error = f"{response.status_code}: {response.text[:200]}"
        if response.status_code != 429:
            break
        _time.sleep(RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1))
    raise AlpacaScreenerError(f"GET {url} -> {last_error}")


def parse_movers(payload: dict) -> tuple[list[dict], list[dict]]:
    """Screener movers response -> (gainers, losers), each {symbol, percent_change, price}.

    The percent_change is kept but must be treated as a CLAIM, not a measurement — see the
    module docstring. Rows without a usable price are dropped rather than defaulted.
    """
    if "gainers" not in payload and "losers" not in payload:
        raise AlpacaScreenerError(
            f"Antwort enthaelt weder 'gainers' noch 'losers': {str(payload)[:200]}"
        )

    def _clean(rows: list[dict] | None) -> list[dict]:
        out = []
        for row in rows or []:
            symbol, price = row.get("symbol"), row.get("price")
            change = row.get("percent_change")
            if not symbol or not price or change is None:
                continue
            out.append({
                "symbol": symbol,
                "percent_change": float(change),
                "price": float(price),
            })
        return out

    return _clean(payload.get("gainers")), _clean(payload.get("losers"))


def parse_most_actives(payload: dict) -> dict[str, dict]:
    """Screener most-actives response -> {symbol: {volume, trade_count}}.

    This is the only place the radar sees SIP volume. It is used as a corroborating
    breadth signal ("the whole market is trading this"), never as the volume ratio — the
    ratio has to compare like with like, and prevDailyBar volume is IEX.
    """
    out: dict[str, dict] = {}
    for row in payload.get("most_actives") or []:
        symbol = row.get("symbol")
        if not symbol:
            continue
        out[symbol] = {
            "volume": float(row.get("volume") or 0.0),
            "trade_count": float(row.get("trade_count") or 0.0),
        }
    return out


def parse_snapshots(payload: dict) -> dict[str, dict]:
    """Snapshots response -> {symbol: {price, prev_close, volume, prev_volume, minute_at}}.

    minute_at is carried through deliberately: a symbol whose latest minute bar is years
    old (FIXX, 2024-03-25) is a dead listing that the screener still ranks. The caller
    needs that timestamp to throw it out.

    A symbol missing either day bar is ABSENT from the result rather than present with
    zeros — absence means "cannot verify", and the caller refuses to trade on it.
    """
    out: dict[str, dict] = {}
    for symbol, snap in (payload or {}).items():
        if not isinstance(snap, dict):
            continue
        day = snap.get("dailyBar") or {}
        prev = snap.get("prevDailyBar") or {}
        minute = snap.get("minuteBar") or {}
        price, prev_close = day.get("c"), prev.get("c")
        if not price or not prev_close:
            continue
        out[symbol] = {
            "price": float(price),
            "prev_close": float(prev_close),
            "volume": float(day.get("v") or 0.0),
            "prev_volume": float(prev.get("v") or 0.0),
            "open": float(day.get("o") or 0.0) or None,
            "high": float(day.get("h") or 0.0) or None,
            "minute_at": minute.get("t"),
            "minute_price": float(minute.get("c") or 0.0) or None,
        }
    return out


def parse_quotes(payload: dict) -> dict[str, dict]:
    """Latest-quotes response -> {symbol: {bid, ask, spread_bp}}.

    spread_bp is computed against the mid. Quotes with a crossed or zero side are dropped:
    an unpriced book is not a tradable book, and a 0-bid would fake a perfect spread.
    """
    out: dict[str, dict] = {}
    for symbol, quote in (payload.get("quotes") or {}).items():
        bid, ask = quote.get("bp"), quote.get("ap")
        if not bid or not ask or bid <= 0 or ask <= 0 or ask < bid:
            continue
        mid = (bid + ask) / 2.0
        out[symbol] = {
            "bid": float(bid),
            "ask": float(ask),
            "bid_size": float(quote.get("bs") or 0.0),
            "ask_size": float(quote.get("as") or 0.0),
            "spread_bp": (ask - bid) / mid * 10_000.0,
        }
    return out


def parse_assets(rows: list[dict]) -> dict[str, dict]:
    """Assets response -> {symbol: {name, exchange, tradable, fractionable, shortable}}.

    Kept as a dict rather than a filtered set because the radar's instrument filter needs
    the NAME: warrants, rights, units and leveraged ETFs are all flagged `tradable` by the
    broker (verified 2026-08-19: TNONW "Tenon Medical Warrant", MRNX "Defiance Daily
    Target 2X Long MRNA ETF"), so only the name distinguishes them.
    """
    out: dict[str, dict] = {}
    for row in rows or []:
        symbol = row.get("symbol")
        if not symbol:
            continue
        out[symbol] = {
            "name": row.get("name") or "",
            "exchange": row.get("exchange") or "",
            "tradable": bool(row.get("tradable")),
            "fractionable": bool(row.get("fractionable")),
            "shortable": bool(row.get("shortable")),
        }
    return out


def fetch_movers(top: int = SCREENER_TOP) -> tuple[list[dict], list[dict]]:
    """Market-wide top gainers and losers (network, SIP-based)."""
    return parse_movers(_get(f"{SCREENER_BASE}/stocks/movers", {"top": top}))


def fetch_most_actives(top: int = SCREENER_TOP) -> dict[str, dict]:
    """Market-wide most active symbols by volume (network, SIP-based)."""
    return parse_most_actives(
        _get(f"{SCREENER_BASE}/stocks/most-actives", {"by": "volume", "top": top})
    )


def fetch_snapshots(symbols: list[str]) -> dict[str, dict]:
    """Day/prev-day/minute bars per symbol (network, IEX) — the independent verification."""
    out: dict[str, dict] = {}
    for start in range(0, len(symbols), SNAPSHOT_CHUNK):
        chunk = symbols[start:start + SNAPSHOT_CHUNK]
        payload = _get(f"{DATA_BASE}/stocks/snapshots",
                       {"symbols": ",".join(chunk), "feed": FEED})
        out.update(parse_snapshots(payload))
    return out


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """Latest bid/ask per symbol (network, IEX) — the tradability check."""
    out: dict[str, dict] = {}
    for start in range(0, len(symbols), SNAPSHOT_CHUNK):
        chunk = symbols[start:start + SNAPSHOT_CHUNK]
        payload = _get(f"{DATA_BASE}/stocks/quotes/latest",
                       {"symbols": ",".join(chunk), "feed": FEED})
        out.update(parse_quotes(payload))
    return out


def fetch_assets() -> dict[str, dict]:
    """All active US equities the broker knows (network, ~14k rows, ~1.6 s).

    Called once per scan run, not per candidate: the list changes on corporate-action
    timescales, and the runner caches it for the day.
    """
    import httpx

    with httpx.Client(headers=auth_headers(), timeout=60.0) as client:
        response = client.get(
            f"{PAPER_BASE}/assets",
            params={"status": "active", "asset_class": "us_equity"},
        )
    if response.status_code != 200:
        raise AlpacaScreenerError(
            f"GET /v2/assets -> {response.status_code}: {response.text[:300]}"
        )
    return parse_assets(response.json())
