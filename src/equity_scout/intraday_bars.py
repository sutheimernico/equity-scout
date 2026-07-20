"""Intraday 15-minute bars for the session lane (vision v11) — with the delay-honesty gate.

yfinance intraday quotes are ~15 minutes DELAYED. The honesty model: a bar is only usable
("settled") once its END lies at least `SETTLE_MINUTES` in the past — 20 minutes, a safety
margin over the 15-minute delay — so the engine's ledger runs on the bar timeline, slightly
behind wall-clock, and can never price off data it could not have seen. Network code is
isolated behind `fetch_bars` (lazy yfinance import, faked in tests); the gate is pure.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

BAR_MINUTES = 15
SETTLE_MINUTES = 20

SESSION_UNIVERSE = (
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD",
    "AVGO", "NFLX",
)


def settled_bars(bars: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Only bars whose END (start + 15 min) is at least SETTLE_MINUTES in the past.
    `bars` is indexed by tz-aware bar START times; `now` must be tz-aware too."""
    if bars.empty:
        return bars
    cutoff = pd.Timestamp(now) - timedelta(minutes=SETTLE_MINUTES)
    ends = bars.index + pd.Timedelta(minutes=BAR_MINUTES)
    return bars.loc[ends <= cutoff]


def fetch_bars(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Today's 15-minute OHLC bars per ticker (network; lazy import keeps tests offline).
    A ticker that fails or returns nothing is simply absent — callers treat absence as
    'no data this run', never as a zero price."""
    import yfinance as yf

    data = yf.download(
        list(tickers), interval="15m", period="1d", auto_adjust=True,
        progress=False, threads=True, group_by="ticker",
    )
    out: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            # group_by="ticker" yields MultiIndex columns even for a single ticker on
            # current yfinance — select by ticker whenever that level exists.
            frame = data[ticker] if isinstance(data.columns, pd.MultiIndex) else data
        except KeyError:
            continue
        frame = frame.dropna(how="any")
        if frame.empty:
            continue
        out[ticker] = frame.rename(columns=str.lower)[["open", "high", "low", "close"]]
    return out
