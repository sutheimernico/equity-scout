"""Cross-sectional momentum with a skip-month (v16 T2): buy the relative winners.

Distinct from the momentum already in this repo, and the distinction is the reason it earns a
place. `DualMomentumStrategy` (GEM) picks ONE asset from a pair and is really a regime switch;
`SectorRotationStrategy` ranks 11 sector ETFs by a 12/6-month blend. This one ranks a WIDE
universe by the academic 12-1 formulation and holds the top slice equal-weighted.

The skip-month is the load-bearing detail. Jegadeesh & Titman (1993) measured momentum over
12 months while EXCLUDING the most recent one, because short-horizon returns reverse: last
month's biggest winner is disproportionately likely to give it back, largely from bid-ask
bounce and liquidity effects. Ranking on a plain 12-month return quietly mixes the momentum
premium with that reversal and gives back part of the edge. Here: return from t-12m to t-1m.

Asness/Moskowitz/Pedersen (2013) show the same premium across asset classes and decades, which
is why this runs on the ETF universe by default rather than on single stocks — and why the
`universe` parameter exists at all (pointing it at the 31-ticker stock panel is possible, but
that panel is today's watchlist and therefore survivorship-biased; see the v16 plan).

Each slot carries an absolute-momentum hurdle against the cash proxy, same convention as GEM
and the sector rotation: relative strength inside a falling market is still a falling book.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


class CrossSectionalMomentumStrategy:
    name = "Cross-Sectional Momentum (12-1)"

    def __init__(
        self,
        universe: tuple[str, ...] = tuple(ETF_TICKERS),
        top_n: int = 4,
        lookback_months: int = 12,
        skip_months: int = 1,
        safe: str = "IEF",
        hurdle: str = "BIL",
        min_rankable: int = 6,
    ) -> None:
        self.universe = universe
        self.top_n = top_n
        self.lookback_months = lookback_months
        self.skip_months = skip_months
        self.safe = safe
        self.hurdle = hurdle
        self.min_rankable = min_rankable

    def _safe_ticker(self, market: MarketView) -> str:
        """Bonds, or the cash proxy when the bond asset has no history — never a guess."""
        return self.safe if market.trailing_return(self.safe, 0) is not None else self.hurdle

    def _skip_momentum(self, market: MarketView, ticker: str) -> float | None:
        """Return from t-`lookback` to t-`skip`, i.e. 12-1 by default.

        Derived from two total returns rather than a price lookup so it goes through the same
        look-ahead-safe accessor as every other strategy: (1+r_long)/(1+r_skip) - 1.
        """
        long_leg = market.trailing_return(ticker, self.lookback_months)
        if long_leg is None:
            return None
        if self.skip_months <= 0:
            return long_leg
        skip_leg = market.trailing_return(ticker, self.skip_months)
        if skip_leg is None or skip_leg <= -1.0:
            return None
        return (1.0 + long_leg) / (1.0 + skip_leg) - 1.0

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        scores = {
            ticker: value
            for ticker in self.universe
            if (value := self._skip_momentum(market, ticker)) is not None
        }
        hurdle = self._skip_momentum(market, self.hurdle)
        if len(scores) < self.min_rankable or hurdle is None:
            return [TargetWeight(self._safe_ticker(market), 1.0)]
        winners = sorted(scores, key=lambda t: scores[t], reverse=True)[: self.top_n]
        slot = 1.0 / self.top_n
        weights: list[TargetWeight] = []
        defensive_slots = 0
        for ticker in winners:
            if scores[ticker] > hurdle:  # absolute momentum, per slot
                weights.append(TargetWeight(ticker, slot))
            else:
                defensive_slots += 1
        if defensive_slots:
            weights.append(TargetWeight(self._safe_ticker(market), slot * defensive_slots))
        return weights
