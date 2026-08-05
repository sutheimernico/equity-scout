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

from datetime import datetime, timedelta, timezone

import pandas as pd

from equity_scout.alpaca_broker import DATA_BASE, auth_headers

RANGE_BAR_MINUTES = 15  # opening range
TRIGGER_BAR_MINUTES = 1  # breakout trigger
FEED = "iex"  # Basic plan: the API default (sip) answers 403


class AlpacaDataError(RuntimeError):
    """The Alpaca feed broke the contract the session lane relies on."""


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
