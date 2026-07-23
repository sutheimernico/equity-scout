"""OHLC panel loader (v13 O1) — the execution-world data source for the Auto-Depot.

The close-only panels stay the SIGNAL world; this module exists so the depot can fill
rebalance trades at the next day's OPEN (v13 O2) and estimate spreads from high/low
ranges (v13 O3). Additive by design: no close-only consumer changes. Shape is the
simplest consumers need: one DataFrame per ticker with open/high/low/close columns and
that ticker's OWN history — a young or gappy ticker never truncates the others (the
combined-panel lesson from v13 R3).

Same seams and conventions as `etf_panel`: read-through CSV snapshot, network behind a
lazy import, tests inject a fake downloader and never touch the network. The snapshot is
long-format (date,ticker,open,high,low,close) — a per-ticker dict does not round-trip
through a wide CSV without MultiIndex headaches.
"""
from __future__ import annotations

import os

import pandas as pd

DEFAULT_OHLC_SNAPSHOT = "data/prices/autotrader_ohlc.csv"
OHLC_FIELDS = ("open", "high", "low", "close")


def _download_ohlc(tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
    """Network: adjusted daily OHLC per ticker. Lazy import keeps tests offline."""
    import yfinance as yf

    data = yf.download(
        tickers, start=start, auto_adjust=True, progress=False, threads=True,
        group_by="ticker",
    )
    panel: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            frame = data[ticker] if len(tickers) > 1 else data
        except KeyError:
            continue  # unknown symbol: absent key, callers count the miss honestly
        frame = frame.rename(columns=str.lower)
        if not set(OHLC_FIELDS).issubset(frame.columns):
            continue
        frame = frame[list(OHLC_FIELDS)].dropna(how="all")
        if not frame.empty:
            panel[ticker] = frame
    return panel


def save_ohlc_snapshot(panel: dict[str, pd.DataFrame], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = []
    for ticker, frame in panel.items():
        out = frame.copy()
        out.insert(0, "ticker", ticker)
        rows.append(out)
    combined = (
        pd.concat(rows) if rows
        else pd.DataFrame(columns=["ticker", *OHLC_FIELDS])
    )
    combined.to_csv(path, index_label="date")


def load_ohlc_snapshot(path: str) -> dict[str, pd.DataFrame]:
    df = pd.read_csv(path, index_col="date", parse_dates=["date"])
    return {
        str(ticker): group.drop(columns="ticker").sort_index()
        for ticker, group in df.groupby("ticker")
    }


def load_ohlc_panel(
    tickers: list[str],
    *,
    start: str,
    snapshot: str = DEFAULT_OHLC_SNAPSHOT,
    refresh: bool = False,
    downloader=_download_ohlc,
) -> dict[str, pd.DataFrame]:
    """Read-through load: snapshot if present (and not `refresh`), else download and
    snapshot. Returns {ticker: OHLC frame}; a symbol that yielded no data is simply
    absent — no crash, no synthetic rows."""
    if not refresh and os.path.exists(snapshot):
        return load_ohlc_snapshot(snapshot)
    panel = downloader(tickers, start)
    save_ohlc_snapshot(panel, snapshot)
    return panel
