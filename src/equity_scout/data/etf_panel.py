"""Load a multi-asset daily price panel from yfinance, with a local CSV snapshot.

Network code is isolated (lazy yfinance import) so tests never touch it; the cleaning transform is
pure and unit-tested. Per the research: `auto_adjust=True` (Close = total-return adjusted),
`repair=True`, daily only, and a frozen CSV snapshot so backtests are reproducible against Yahoo's
silently-changing history. Returns are computed from these adjusted closes (correct for comparing
allocation strategies — see `market.py`).
"""
from __future__ import annotations

import os

import pandas as pd

from equity_scout.market import PricePanel

DEFAULT_SNAPSHOT = "data/prices/etf_panel.csv"


def clean_panel(closes: pd.DataFrame) -> PricePanel:
    """Pure: trim to the common range where every ticker has data, forward-fill stray gaps.

    Truncates to the latest first-trading-day across tickers (so the backtest starts only when all
    assets exist — no synthetic history), then forward-fills isolated holidays and drops anything
    still missing. Dead tickers (all-NaN: delisted / junk symbols) are dropped first — one dead
    column must not crash (first_valid_index=None) or empty the whole panel."""
    if closes.empty:
        return PricePanel(closes)
    closes = closes.dropna(axis=1, how="all")
    if closes.empty:
        return PricePanel(closes)
    first_valid = max(closes[col].first_valid_index() for col in closes.columns)
    trimmed = closes.loc[first_valid:].ffill().dropna(how="any")
    return PricePanel(trimmed)


def drop_short_history(
    closes: pd.DataFrame, *, max_span_loss: float = 0.30
) -> tuple[pd.DataFrame, list[dict]]:
    """Pure: drop columns whose late start would cost the panel too much history (v13 Q1).

    `clean_panel` trims to the LATEST first-valid date across columns, so one young ticker
    (a fresh IPO on the watchlist) silently truncates every other ticker's history — the
    walk-forward trainer then starves on monthly split dates. Explicit rule: a ticker whose
    first valid price would cut more than `max_span_loss` of the panel's full span (earliest
    first-valid to last row, calendar days) is excluded. The column with the earliest start
    always survives (loss 0), so this can never empty a non-empty frame. Returns the
    surviving columns plus exclusion records for the caller to log — silence is the bug."""
    closes = closes.dropna(axis=1, how="all")
    if closes.empty:
        return closes, []
    first_valid = {col: closes[col].first_valid_index() for col in closes.columns}
    panel_start = min(first_valid.values())
    span_days = (closes.index[-1] - panel_start).days
    if span_days <= 0:
        return closes, []
    excluded: list[dict] = []
    keep: list[str] = []
    for col, first in first_valid.items():
        span_loss = (first - panel_start).days / span_days
        if span_loss > max_span_loss:
            excluded.append({
                "ticker": col,
                "first_valid": first.date().isoformat(),
                "panel_start": panel_start.date().isoformat(),
                "span_loss": span_loss,
            })
        else:
            keep.append(col)
    return closes[keep], excluded


def clean_columns(closes: pd.DataFrame) -> PricePanel:
    """Pure: drop dead (all-NaN) columns, forward-fill stray gaps, keep each column's OWN history.

    No common-range trim: for per-pair measurements (person track records, ledger resolves) one
    young IPO or junk ticker must not truncate every other ticker's usable history — consumers
    align pair-wise (`closes[[ticker, benchmark]].dropna()`) themselves."""
    return PricePanel(closes.dropna(axis=1, how="all").ffill())


def save_snapshot(panel: PricePanel, path: str = DEFAULT_SNAPSHOT) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    panel.closes.to_csv(path, index_label="date")


def load_snapshot(path: str = DEFAULT_SNAPSHOT) -> PricePanel:
    df = pd.read_csv(path, index_col="date", parse_dates=["date"])
    return PricePanel(df)


def _scipy_available() -> bool:
    try:
        import scipy  # noqa: F401  (yfinance's repair=True needs scipy)

        return True
    except ImportError:
        return False


def _download_closes(tickers: list[str], start: str) -> pd.DataFrame:
    """Network: fetch adjusted daily closes for the basket. Lazy import keeps tests offline.

    `repair=True` cleans known Yahoo glitches but needs scipy; we enable it only when scipy is
    present (it arrives with the ML phases) — broad US ETFs rarely need repair anyway.
    """
    import yfinance as yf

    data = yf.download(
        tickers, start=start, auto_adjust=True, repair=_scipy_available(), progress=False, threads=True
    )
    closes = data["Close"]  # auto_adjust puts the total-return-adjusted price in Close
    if isinstance(closes, pd.Series):  # single ticker → Series; normalise to a frame
        closes = closes.to_frame(tickers[0])
    return closes[tickers]  # stable column order


def load_etf_panel(
    tickers: list[str],
    *,
    start: str = "2007-01-01",
    snapshot: str = DEFAULT_SNAPSHOT,
    refresh: bool = False,
) -> PricePanel:
    """Load from the CSV snapshot if present, else fetch from yfinance and snapshot it."""
    if not refresh and os.path.exists(snapshot):
        return load_snapshot(snapshot)
    panel = clean_panel(_download_closes(tickers, start))
    save_snapshot(panel, snapshot)
    return panel


def load_price_history(
    tickers: list[str],
    *,
    start: str,
    snapshot: str,
    refresh: bool = True,
) -> PricePanel:
    """Column-wise variant of load_etf_panel (clean_columns instead of clean_panel) for
    per-pair measurements over heterogeneous tickers. Missing symbols simply yield no
    column — callers count those honestly as unresolvable."""
    if not refresh and os.path.exists(snapshot):
        return load_snapshot(snapshot)
    panel = clean_columns(_download_closes(tickers, start))
    save_snapshot(panel, snapshot)
    return panel
