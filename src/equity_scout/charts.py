"""One-year price chart PNGs for Telegram pitch photos.

Rendering is pure (data in, PNG bytes out; matplotlib Agg backend, no display);
fetching is a thin yfinance seam kept separate so tests never touch the network.
"""
from __future__ import annotations

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (backend must be set before pyplot import)


def fetch_year_closes(ticker: str) -> tuple[list[datetime], list[float]]:
    """One year of daily closes from yfinance. Raises on network/symbol failure —
    the caller (photo sender) falls back to a text-only pitch."""
    import yfinance as yf

    hist = yf.Ticker(ticker).history(period="1y", interval="1d")
    if hist.empty:
        raise ValueError(f"no price history for {ticker}")
    dates = [d.to_pydatetime() for d in hist.index]
    closes = [float(c) for c in hist["Close"].tolist()]
    return dates, closes


def year_return(closes: list[float]) -> float | None:
    """Total return over the series, or None when there is not enough data."""
    if len(closes) < 2 or closes[0] <= 0:
        return None
    return closes[-1] / closes[0] - 1.0


def render_year_chart(ticker: str, dates: list[datetime], closes: list[float]) -> bytes:
    """Clean single-line 1y chart as PNG bytes (Telegram photo)."""
    if not closes:
        raise ValueError("no closes to plot")
    up = closes[-1] >= closes[0]
    color = "#1a7f37" if up else "#b62324"
    fig, ax = plt.subplots(figsize=(9, 4), dpi=110)
    ax.plot(dates, closes, color=color, linewidth=1.8)
    ax.fill_between(dates, closes, min(closes), color=color, alpha=0.08)
    change = year_return(closes)
    change_label = f" · 1 Jahr {change * 100:+.0f} %" if change is not None else ""
    ax.set_title(f"{ticker} — Kurs 1 Jahr{change_label}", loc="left", fontsize=12)
    ax.grid(True, alpha=0.25, linewidth=0.5)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.annotate(f"{closes[-1]:,.2f}", xy=(dates[-1], closes[-1]),
                xytext=(6, 0), textcoords="offset points", fontsize=10, color=color)
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    return buffer.getvalue()
