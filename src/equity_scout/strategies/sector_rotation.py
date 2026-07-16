"""Sector momentum rotation over the 11 SPDR Select Sector ETFs (v8 B1).

Classic sector rotation (Faber/Quantpedia lineage): rank the sectors by trailing
momentum — here the mean of the 12- and 6-month returns, one fast and one slow leg —
hold the top N equal-weighted, rebalance monthly (the engine's cadence). Each winner
must ALSO beat the T-bill hurdle (absolute momentum, same crash switch as GEM);
a slot that fails goes to bonds instead. Sectors without a full lookback (XLRE
pre-2015, XLC pre-2018) are skipped, never guessed; if too few sectors are rankable
the whole book sits defensively.

Evidence (research 2026-07-16): Quantpedia's 1928-2009 backtest of top-3-of-10 by
12m momentum shows equity-like returns with ~10 points less max drawdown than
buy-and-hold. No alpha promise — this is a disciplined process on display.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.etf_universe import SECTOR_ETF_TICKERS
from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


class SectorRotationStrategy:
    name = "Sektor-Rotation (Top 3)"

    def __init__(
        self,
        sectors: tuple[str, ...] = tuple(SECTOR_ETF_TICKERS),
        top_n: int = 3,
        safe: str = "IEF",
        hurdle: str = "BIL",
        lookback_months: tuple[int, ...] = (12, 6),
        min_rankable: int = 6,
    ) -> None:
        self.sectors = sectors
        self.top_n = top_n
        self.safe = safe
        self.hurdle = hurdle
        self.lookback_months = lookback_months
        self.min_rankable = min_rankable

    def _safe_ticker(self, market: MarketView) -> str:
        """Bonds, or the cash proxy when the bond asset has no history — same
        never-guess fallback as DualMomentumStrategy._defensive."""
        return self.safe if market.trailing_return(self.safe, 0) is not None else self.hurdle

    def _blend_momentum(self, market: MarketView, ticker: str) -> float | None:
        values: list[float] = []
        for months in self.lookback_months:
            value = market.trailing_return(ticker, months)
            if value is None:
                return None
            values.append(value)
        return sum(values) / len(values)

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        momentum = {
            ticker: blend
            for ticker in self.sectors
            if (blend := self._blend_momentum(market, ticker)) is not None
        }
        hurdle_momentum = self._blend_momentum(market, self.hurdle)
        if len(momentum) < self.min_rankable or hurdle_momentum is None:
            return [TargetWeight(self._safe_ticker(market), 1.0)]
        winners = sorted(momentum, key=lambda t: momentum[t], reverse=True)[: self.top_n]
        slot = 1.0 / self.top_n
        weights: list[TargetWeight] = []
        defensive_slots = 0
        for ticker in winners:
            if momentum[ticker] > hurdle_momentum:  # absolute momentum per slot
                weights.append(TargetWeight(ticker, slot))
            else:
                defensive_slots += 1
        if defensive_slots:
            weights.append(TargetWeight(self._safe_ticker(market), slot * defensive_slots))
        return weights
