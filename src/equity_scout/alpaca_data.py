"""Real-time IEX bars for the session lane (2026-08-04, revised 2026-08-05).

Replaces the yfinance path for lane `session`, whose ~15-minute delay forced a 20-minute
settle margin and produced fills at prices that were no longer available when the decision
was made (executability bias — see
docs/superpowers/specs/2026-08-04-session-lane-realtime-broker-design.md).

Two resolutions, two roles (design decision 5 in the plan): the opening range is built from
15-minute bars, which want breadth and do not care about immediacy, while the breakout
trigger runs on 1-minute bars, where aggregation is precisely the cost. Density on the
1-minute feed was measured on 2026-08-05 before any of this was built — 9 of 10 session
tickers print in 100 % of regular-session minutes, QQQ in 98 %.

The delay is gone, the completeness rule is not: a bar is usable once its interval has
ELAPSED, never while it is still forming. `intraday_bars.settled_bars` stays untouched for
the other feed; this module owns the Alpaca-side gate.

Network code lives in `fetch_bars` alone and is faked in tests — same structure as
`intraday_bars`.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

from equity_scout.alpaca_broker import DATA_BASE, auth_headers

RANGE_BAR_MINUTES = 15  # opening range
TRIGGER_BAR_MINUTES = 1  # breakout trigger
FEED = "iex"  # Basic plan: the API default (sip) answers 403

# US regular session in New York wall-clock. The lane trades this window only, and — unlike
# yfinance, which handed the other feed a regular-session-only frame for free — Alpaca
# returns every print in the requested window, pre- and after-hours included.
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)


class AlpacaDataError(RuntimeError):
    """The Alpaca feed broke the contract the session lane relies on."""


# Yahoo exchange suffixes for venues Alpaca does not carry. The EU half is imported from
# universe.py rather than copied; the rest are the non-EU venues our watchlist actually
# produces. Deliberately a suffix ALLOW-list and not `"." in ticker`: US class shares
# (BRK.B, BF.B) carry a dot too, and dropping them would shrink the universe in silence.
_NON_US_SUFFIXES = frozenset({"HK", "T", "NS", "AX", "SA", "TO", "KS", "SS", "SZ", "NZ"})


def us_symbols(tickers: list[str]) -> list[str]:
    """The subset Alpaca can be asked about at all, sorted.

    A single unknown symbol makes the whole multi-symbol request answer 400, so a caller
    that passes a foreign listing loses every US quote in the same batch — which is how
    the gap-fade lane spent its first four trading days placing no orders at all.
    """
    from equity_scout.universe import _SUFFIX_COUNTRY

    foreign = _NON_US_SUFFIXES | set(_SUFFIX_COUNTRY)

    def is_us(ticker: str) -> bool:
        _, dot, suffix = ticker.rpartition(".")
        # No dot at all is decided before the suffix is ever consulted — otherwise plain
        # US tickers that happen to spell a venue (T = AT&T, L = Loews) would be dropped.
        return not dot or suffix not in foreign

    return sorted(t for t in tickers if is_us(t))


def parse_bars(payload: dict) -> dict[str, pd.DataFrame]:
    """Alpaca's multi-symbol bar response -> the intraday_bars DataFrame contract.

    A symbol with no bars is ABSENT from the result, never present with zeros: callers
    read absence as 'no data this run' and refuse to trade on it.
    """
    if "bars" not in payload:
        raise AlpacaDataError(
            f"Antwort enthaelt kein 'bars' — Feed oder Plan falsch: {str(payload)[:200]}"
        )
    out: dict[str, pd.DataFrame] = {}
    for ticker, series in (payload["bars"] or {}).items():
        if not series:
            continue
        frame = pd.DataFrame(
            [
                {"open": b["o"], "high": b["h"], "low": b["l"],
                 "close": b["c"], "volume": b["v"]}
                for b in series
            ],
            index=pd.DatetimeIndex([pd.Timestamp(b["t"]) for b in series], tz="UTC"),
        ).sort_index()
        out[ticker] = frame.tz_convert("America/New_York")
    return out


def complete_bars(bars: pd.DataFrame, now: datetime, *, bar_minutes: int) -> pd.DataFrame:
    """Only bars whose interval has fully elapsed. With a real-time feed this is the whole
    gate — no safety margin is needed for a delay that no longer exists.

    `bar_minutes` is an argument rather than a module constant because the lane gates two
    resolutions at once and a bar's completeness is a statement about its own interval.
    """
    if bars.empty:
        return bars
    ends = bars.index + pd.Timedelta(minutes=bar_minutes)
    return bars.loc[ends <= pd.Timestamp(now)]


def regular_session_bars(
    bars: pd.DataFrame, *, session_date: date | None = None
) -> pd.DataFrame:
    """Bars of ONE regular session (09:30-16:00 ET) — by default the newest day present.

    This gate is what keeps `st_session.opening_range` meaningful: it takes the FIRST TWO
    BARS of the frame it is handed, so on a raw Alpaca frame the "opening range" would be a
    07:xx pre-market range on thin volume — and the lane's stop, target and position size all
    derive from that number. Restricting to one day matters for the same reason: an 8-hour
    window opened before the bell still reaches into yesterday's session.
    """
    if bars.empty:
        return bars
    times = bars.index.time
    within = (times >= SESSION_OPEN) & (times < SESSION_CLOSE)
    session_only = bars.loc[within]
    if session_only.empty:
        return session_only
    day = session_date or session_only.index[-1].date()
    return session_only.loc[session_only.index.date == day]


def parse_latest_trades(payload: dict) -> dict[str, tuple[float, datetime]]:
    """Alpaca's latest-trades response -> {ticker: (price, traded_at)}.

    Gap-fade lane (2026-08-17): the pre-market signal is the latest IEX print. A ticker
    without a pre-market trade is ABSENT from the result, never present with a zero —
    absence means 'no signal', and the caller's quote-age gate handles stale prints.
    """
    if "trades" not in payload:
        raise AlpacaDataError(
            f"Antwort enthaelt kein 'trades' — Feed oder Plan falsch: {str(payload)[:200]}"
        )
    out: dict[str, tuple[float, datetime]] = {}
    for ticker, trade in (payload["trades"] or {}).items():
        price = (trade or {}).get("p")
        stamp = (trade or {}).get("t")
        if not price or not stamp:
            continue
        out[ticker] = (float(price), pd.Timestamp(stamp).to_pydatetime())
    return out


def fetch_latest_trades(tickers: list[str]) -> dict[str, tuple[float, datetime]]:
    """Latest IEX trade per ticker (network) — pre-market prints included.

    Raises AlpacaDataError on any non-200, same stance as fetch_bars: a silent empty
    result would look exactly like 'no gap today'.
    """
    import httpx

    with httpx.Client(headers=auth_headers(), timeout=30.0) as client:
        response = client.get(
            f"{DATA_BASE}/stocks/trades/latest",
            params={"symbols": ",".join(tickers), "feed": FEED},
        )
    if response.status_code != 200:
        raise AlpacaDataError(
            f"GET /v2/stocks/trades/latest -> {response.status_code}: {response.text[:300]}"
        )
    return parse_latest_trades(response.json())


def fetch_bars(
    tickers: list[str], *, now: datetime, bar_minutes: int, hours: int = 8
) -> dict[str, pd.DataFrame]:
    """Recent IEX bars per ticker at the given resolution (network).

    Raises AlpacaDataError on any non-200 — a silent empty result would look exactly like
    'no signal today'.
    """
    import httpx

    # UTC explicitly, NOT astimezone(tz=None): that converts to the machine's local zone
    # while the "Z" suffix claims UTC, which silently shifts the window by the local offset
    # (two hours in Berlin summer) and would ask Alpaca for the wrong slice of the session.
    start = (now - timedelta(hours=hours)).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with httpx.Client(headers=auth_headers(), timeout=30.0) as client:
        response = client.get(
            f"{DATA_BASE}/stocks/bars",
            params={
                "symbols": ",".join(tickers),
                "timeframe": f"{bar_minutes}Min",
                "start": start,
                "feed": FEED,
                "limit": 10_000,
            },
        )
    if response.status_code != 200:
        raise AlpacaDataError(
            f"GET /v2/stocks/bars ({bar_minutes}Min) -> "
            f"{response.status_code}: {response.text[:300]}"
        )
    return parse_bars(response.json())
