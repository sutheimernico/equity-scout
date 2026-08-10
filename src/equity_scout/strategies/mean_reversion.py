"""Short-horizon mean reversion (v16 T3): buy what fell hardest — but only in an uptrend.

The deliberate counterweight to `CrossSectionalMomentumStrategy`. That one buys relative
winners over 12 months; this one buys relative LOSERS over days. Both cannot be right about
the same asset at the same time, and that is the point: two families whose errors are
negatively correlated add more to a portfolio than two variants of the same idea. This is why
the family exists here and not as another momentum knob.

Mechanism, stated plainly: over horizons of days to a few weeks, prices that gap away from
their own moving average tend to snap back — liquidity provision gets paid (Lehmann 1990;
Lo & MacKinlay 1990). The effect is real and small, and it is the FIRST thing costs eat: a
strategy that trades weekly on a 1 % edge pays most of it away in spread. It is measured here
against the same Corwin-Schultz cost floor as everything else, not assumed.

The regime filter is the difference between a reversion strategy and a falling knife. Buying
the biggest losers works when the market itself is above its long-term trend; in a bear market
"fell hardest" selects the names that keep falling. So: market proxy below its 200-day average
-> the whole book goes defensive, no exceptions.

Scoring uses a z-score of the distance to the moving average, NOT the raw return, so that a
calm asset 3 % below its mean ranks ahead of a volatile one 5 % below. Without the volatility
normalisation this strategy silently becomes "hold the most volatile assets".
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView

TRADING_DAYS_PER_MONTH = 21
# 10 days: the horizon over which the snap-back is documented. Long enough to be more than
# noise, short enough that the position is not a de-facto momentum bet.
REVERSION_WINDOW_DAYS = 10
# The market's own trend filter. 200 days is the conventional line and is used here for the
# same reason the repo uses it in `regime.py` — one definition, not a second private one.
TREND_WINDOW_DAYS = 200
MIN_PLAUSIBLE_VOL = 0.005


class MeanReversionStrategy:
    name = "Mean-Reversion (10 Tage)"

    def __init__(
        self,
        universe: tuple[str, ...] = tuple(ETF_TICKERS),
        top_n: int = 3,
        market_proxy: str = "SPY",
        safe: str = "BIL",
        reversion_window_days: int = REVERSION_WINDOW_DAYS,
        trend_window_days: int = TREND_WINDOW_DAYS,
        min_rankable: int = 6,
    ) -> None:
        self.universe = universe
        self.top_n = top_n
        self.market_proxy = market_proxy
        self.safe = safe
        self.reversion_window_days = reversion_window_days
        self.trend_window_days = trend_window_days
        self.min_rankable = min_rankable

    def _market_is_in_uptrend(self, market: MarketView) -> bool | None:
        """True/False, or None when the trend cannot be established (then: no trading)."""
        series = market.history(self.market_proxy).dropna()
        if len(series) < self.trend_window_days:
            return None
        window = series.iloc[-self.trend_window_days:]
        average = float(window.mean())
        latest = float(series.iloc[-1])
        if average <= 0 or not math.isfinite(average) or not math.isfinite(latest):
            return None
        return latest > average

    def _reversion_z(self, market: MarketView, ticker: str) -> float | None:
        """How many daily standard deviations the price sits BELOW its own moving average.
        Positive = oversold (a candidate); negative = above its mean (not a candidate)."""
        series = market.history(ticker).dropna()
        if len(series) < self.reversion_window_days + 2:
            return None
        window = series.iloc[-self.reversion_window_days:]
        average = float(window.mean())
        latest = float(series.iloc[-1])
        if average <= 0 or not math.isfinite(average) or not math.isfinite(latest):
            return None
        returns = series.iloc[-(self.reversion_window_days + 1):].pct_change().dropna()
        if len(returns) < 2:
            return None
        daily_vol = float(returns.std(ddof=1))
        # A near-zero vol means a stale feed, not a stable asset — dividing by it would
        # manufacture a huge z-score and hand the book to a broken series.
        if not math.isfinite(daily_vol) or daily_vol < MIN_PLAUSIBLE_VOL / math.sqrt(252):
            return None
        return (average / latest - 1.0) / daily_vol

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        uptrend = self._market_is_in_uptrend(market)
        if uptrend is not True:
            # Unknown trend or a downtrend: reversion turns into catching falling knives.
            return [TargetWeight(self.safe, 1.0)] if market.last_price(self.safe) else []
        scores = {
            ticker: value
            for ticker in self.universe
            if ticker != self.safe
            and (value := self._reversion_z(market, ticker)) is not None
        }
        if len(scores) < self.min_rankable:
            return [TargetWeight(self.safe, 1.0)] if market.last_price(self.safe) else []
        # Only genuinely oversold names qualify. Without this the strategy would buy the
        # "least overbought" assets in a broad rally, which is not the documented effect.
        oversold = [t for t in sorted(scores, key=lambda t: scores[t], reverse=True)
                    if scores[t] > 0.0][: self.top_n]
        if not oversold:
            return [TargetWeight(self.safe, 1.0)] if market.last_price(self.safe) else []
        slot = 1.0 / self.top_n  # unfilled slots stay in cash rather than concentrating
        return [TargetWeight(t, slot) for t in oversold]
