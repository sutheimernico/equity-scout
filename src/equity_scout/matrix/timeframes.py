"""Resample 1-minute bars onto the matrix's time-slice axis — 1 minute to 1 month.

Two regimes, one function, because the correct grouping differs:

- **Intraday slices** (1-60 min) are grouped by TRADING DAY first. A plain `resample("5min")`
  over a multi-day frame produces bars that weld 15:59 to the next day's 09:30, i.e. the
  overnight move lands inside an intraday signal. That is exactly the confound the ORB studies
  had to strip out by hand.
- **Swing slices** (day, week, month) must NOT be grouped that way — their whole point is to
  span sessions. They resample the full series directly.

The axis is ordered labels rather than raw minutes because the plateau finder needs a notion of
"the next slice up", and 60 min -> 1 day is not a numeric step (a trading day is 390 minutes,
but a bar labelled 1D also carries the overnight gap the 390-minute bar would not).
"""
from __future__ import annotations

import pandas as pd

# Ordered coarse-to-fine axis. Neighbourhood in the plateau finder = adjacent entries here.
TIME_SLICES: tuple[str, ...] = ("1min", "5min", "15min", "30min", "60min", "1D", "1W", "1M")
INTRADAY_SLICES: tuple[str, ...] = ("1min", "5min", "15min", "30min", "60min")
_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
_PANDAS_FREQ = {"1D": "1D", "1W": "1W", "1M": "1ME"}


def slice_minutes(slice_label: str) -> int:
    """Minutes per bar, for the intraday slices only. Raises for swing labels — they have no
    fixed minute count (a trading day is 390 minutes but a 1D bar spans 1440)."""
    if slice_label not in INTRADAY_SLICES:
        raise ValueError(f"{slice_label} ist keine Intraday-Scheibe")
    return int(slice_label.removesuffix("min"))


def resample_bars(
    bars: pd.DataFrame, slice_label: str, *, keep_incomplete: bool = True
) -> pd.DataFrame:
    """1-minute OHLCV -> bars of `slice_label`.

    `keep_incomplete=False` drops a trailing bar built from fewer source bars than the slice
    needs — use it when a signal's economics depend on the bar being a full interval. It only
    applies to intraday slices; a swing bar's source count varies legitimately (holidays,
    half days), so dropping "short" weeks would silently delete real market periods.
    """
    if bars.empty:
        return bars
    if slice_label == "1min":
        return bars
    if slice_label in _PANDAS_FREQ:
        aggregated = bars.resample(_PANDAS_FREQ[slice_label]).agg(_AGG)
        return aggregated.dropna(subset=["open", "close"])

    minutes = slice_minutes(slice_label)
    local_day = bars.index.tz_convert("America/New_York").date
    pieces = []
    for _, group in bars.groupby(local_day):
        agg = group.resample(f"{minutes}min", origin="start").agg(_AGG)
        if not keep_incomplete:
            counts = group.resample(f"{minutes}min", origin="start").size()
            agg = agg.loc[counts == minutes]
        pieces.append(agg.dropna(subset=["open", "close"]))
    return pd.concat(pieces).sort_index() if pieces else bars.iloc[0:0]
