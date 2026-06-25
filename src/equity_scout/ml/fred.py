"""FRED macro regime features via the public fredgraph CSV — no API key, no extra dependency.

Pulls VIX, the 10y–2y term spread, and the high-yield credit spread (classic macro regime signals)
and aligns them to the price panel dates (forward-filled, since macro series have gaps and publish
lags). Cached to a CSV snapshot like the ETF panel. On any network or parse failure it degrades to an
empty frame, so the meta-model simply runs without these features rather than crashing.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

# feature name -> FRED series id
FRED_SERIES = {
    "vix": "VIXCLS",  # CBOE volatility index
    "term_spread": "T10Y2Y",  # 10Y minus 2Y treasury yield
    "hy_spread": "BAMLH0A0HYM2",  # ICE BofA US high-yield option-adjusted spread
}
FRED_FEATURE_NAMES = tuple(FRED_SERIES.keys())
DEFAULT_FRED_SNAPSHOT = "data/prices/fred.csv"
_BASE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def fred_available(snapshot: str | Path = DEFAULT_FRED_SNAPSHOT) -> bool:
    """True if a FRED snapshot exists locally — gates whether the search space includes FRED features."""
    return Path(snapshot).exists()


def _fetch_series(series_id: str, start: str) -> pd.Series | None:
    try:
        import httpx

        resp = httpx.get(_BASE_URL, params={"id": series_id, "cosd": start}, timeout=20.0)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
    except Exception:
        return None
    if df.shape[1] < 2:
        return None
    df.columns = ["date", "value"]
    series = pd.to_numeric(df["value"], errors="coerce")  # FRED uses "." for missing → NaN
    series.index = pd.to_datetime(df["date"])
    return series.dropna()


def load_fred_features(
    dates: pd.DatetimeIndex,
    *,
    start: str = "2007-01-01",
    snapshot: str | Path = DEFAULT_FRED_SNAPSHOT,
    refresh: bool = False,
) -> pd.DataFrame:
    """FRED features aligned (forward-filled) to `dates`. Empty frame (no columns) if unavailable —
    callers treat that as "no FRED features"."""
    path = Path(snapshot)
    if path.exists() and not refresh:
        raw = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        cols = {name: s for name, sid in FRED_SERIES.items() if (s := _fetch_series(sid, start)) is not None}
        if not cols:
            return pd.DataFrame(index=dates)
        raw = pd.DataFrame(cols).sort_index()
        path.parent.mkdir(parents=True, exist_ok=True)
        raw.to_csv(path)
    if raw.empty:
        return pd.DataFrame(index=dates)
    return raw.reindex(raw.index.union(dates)).ffill().reindex(dates)
