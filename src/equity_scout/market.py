"""Multi-asset price panels and a look-ahead-safe view over them.

A `PricePanel` holds adjusted (total-return) daily closes for a basket of tickers. A `MarketView`
exposes the panel *as of* a decision date and only ever reveals data strictly before that date —
so a strategy physically cannot peek at the price it is about to trade on. This is the structural
guard behind the `position[t] = decide(data < t)` rule; the engine builds one view per rebalance.

Returns are computed from adjusted close (splits + dividends), which is the correct basis for
comparing allocation strategies — price-only return would systematically favour non-distributors
(SPY) over coupon-heavy holdings (TLT/IEF). Trading costs are charged on turnover (weight changes),
so raw close / share-count bookkeeping is not needed here.
"""
from __future__ import annotations

import math

import pandas as pd

TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21


class PricePanel:
    """Daily adjusted closes for a basket: index = dates, columns = tickers."""

    def __init__(self, closes: pd.DataFrame) -> None:
        if not isinstance(closes.index, pd.DatetimeIndex):
            closes = closes.copy()
            closes.index = pd.to_datetime(closes.index)
        self.closes = closes.sort_index()

    @property
    def tickers(self) -> list[str]:
        return list(self.closes.columns)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.closes.index

    def daily_returns(self) -> pd.DataFrame:
        """Per-ticker daily simple returns. First row is dropped (no prior price)."""
        return self.closes.pct_change().iloc[1:]

    def rebalance_dates(self, freq: str = "ME") -> pd.DatetimeIndex:
        """Last available trading day in each period (default monthly). These are real panel
        dates, so the engine can match them exactly."""
        marks = self.closes.resample(freq).last().index
        # resample marks are period-ends (e.g. calendar month-end); snap each to the last actual
        # trading day on or before it that exists in the panel.
        actual = []
        for mark in marks:
            prior = self.closes.index[self.closes.index <= mark]
            if len(prior):
                actual.append(prior[-1])
        return pd.DatetimeIndex(actual).unique()


class MarketView:
    """A panel restricted to data strictly before `as_of`. Strategies see only the past."""

    def __init__(self, panel: PricePanel, as_of: pd.Timestamp) -> None:
        as_of = pd.Timestamp(as_of)
        self._visible = panel.closes.loc[panel.closes.index < as_of]
        self.as_of = as_of

    @property
    def has_data(self) -> bool:
        return len(self._visible) > 0

    @property
    def latest_date(self) -> pd.Timestamp | None:
        return self._visible.index[-1] if self.has_data else None

    @property
    def first_date(self) -> pd.Timestamp | None:
        """Earliest visible date — the panel start. Lets a time-phased strategy (DCA) derive how
        far it is into its schedule without carrying account state."""
        return self._visible.index[0] if self.has_data else None

    def last_price(self, ticker: str) -> float | None:
        if ticker not in self._visible.columns or self._visible.empty:
            return None
        series = self._visible[ticker].dropna()
        return float(series.iloc[-1]) if len(series) else None

    def trailing_return(self, ticker: str, months: int) -> float | None:
        """Total return over the trailing `months` (21 trading days each). None if not enough
        history or a non-positive price would make the ratio meaningless."""
        if ticker not in self._visible.columns:
            return None
        series = self._visible[ticker].dropna()
        lookback = months * TRADING_DAYS_PER_MONTH
        if len(series) < lookback + 1:
            return None
        now = float(series.iloc[-1])
        then = float(series.iloc[-1 - lookback])
        if then <= 0 or not math.isfinite(now) or not math.isfinite(then):
            return None
        return now / then - 1.0

    def realised_vol(self, ticker: str, window_days: int = TRADING_DAYS_PER_MONTH) -> float | None:
        """Annualised stdev of daily returns over the trailing window. None if too little data."""
        if ticker not in self._visible.columns:
            return None
        series = self._visible[ticker].dropna()
        if len(series) < window_days + 1:
            return None
        rets = series.iloc[-(window_days + 1):].pct_change().dropna()
        if len(rets) < 2:
            return None
        return float(rets.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
