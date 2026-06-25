"""Recent daily price history for a single ticker via yfinance — feeds the per-stock charts.

Returns adjusted closes plus the latest price and 1-day / period change. yfinance is a lazy import
(keeps tests offline) and any failure degrades to None so the UI can show a quiet fallback.
"""
from __future__ import annotations


def fetch_quote_history(ticker: str, *, period: str = "6mo") -> dict | None:
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    except Exception:
        return None
    if hist is None or "Close" not in hist:
        return None
    closes = [[d.date().isoformat(), round(float(c), 2)] for d, c in hist["Close"].dropna().items()]
    if len(closes) < 2:
        return None
    last, prev, first = closes[-1][1], closes[-2][1], closes[0][1]
    return {
        "ticker": ticker,
        "closes": closes,
        "last": last,
        "change_1d": round((last / prev - 1.0) * 100, 2) if prev else 0.0,
        "change_period": round((last / first - 1.0) * 100, 2) if first else 0.0,
    }
