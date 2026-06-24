"""Defensive Asset Allocation (Keller & Keuning 2018) — the showpiece: rule-based crash protection.

A separate 'canary' universe (VWO + BND) is an early-warning breadth signal. The cash fraction scales
with how many canary assets have negative 13612W momentum: none bad → fully offensive, one → half
defensive, both → fully defensive. The offensive budget is spread equally over the top-N momentum
risk assets (diversified, not a single concentrated bet); the defensive budget goes to the single
top-momentum safe asset.

13612W momentum = 12*r1 + 4*r3 + 2*r6 + 1*r12 (Keller's weighted, faster-responding momentum; the
weights annualise the shorter look-backs). Source: Keller & Keuning, 'Breadth Momentum and the
Canary Universe' (2018). The universes fit this project's ETF basket and are documented here — a
faithful implementation of the method (G6/T3-style), not a specific published parameterisation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


def momentum_13612w(market: MarketView, ticker: str) -> float | None:
    """Keller's weighted momentum. None if any look-back lacks history."""
    r1 = market.trailing_return(ticker, 1)
    r3 = market.trailing_return(ticker, 3)
    r6 = market.trailing_return(ticker, 6)
    r12 = market.trailing_return(ticker, 12)
    if r1 is None or r3 is None or r6 is None or r12 is None:
        return None
    return 12.0 * r1 + 4.0 * r3 + 2.0 * r6 + r12


class DefensiveAssetAllocationStrategy:
    name = "Defensive Asset Allocation"

    def __init__(
        self,
        offensive: tuple[str, ...] = ("SPY", "VEU", "VWO", "VNQ", "GLD", "DBC"),
        defensive: tuple[str, ...] = ("IEF", "TLT", "BND", "BIL"),
        canary: tuple[str, ...] = ("VWO", "BND"),
        top_n: int = 3,
    ) -> None:
        self.offensive = offensive
        self.defensive = defensive
        self.canary = canary
        self.top_n = top_n

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        canary_moms = [momentum_13612w(market, c) for c in self.canary]
        if any(m is None for m in canary_moms):
            return self._all_cash(market)  # not enough history → don't guess
        bad = sum(1 for m in canary_moms if m is not None and m <= 0)
        cash_fraction = min(1.0, bad / len(self.canary))

        weights: list[TargetWeight] = []
        if cash_fraction < 1.0:
            top = self._top_n(market, self.offensive, self.top_n)
            if top:
                each = (1.0 - cash_fraction) / len(top)
                weights.extend(TargetWeight(ticker, each) for ticker in top)
        if cash_fraction > 0.0:
            best_defensive = self._top_n(market, self.defensive, 1)
            if best_defensive:
                weights.append(TargetWeight(best_defensive[0], cash_fraction))
        return weights or self._all_cash(market)

    def _top_n(self, market: MarketView, universe: tuple[str, ...], n: int) -> list[str]:
        moms = {a: momentum_13612w(market, a) for a in universe}
        ranked = sorted((a for a, m in moms.items() if m is not None), key=lambda a: moms[a], reverse=True)  # type: ignore[index,arg-type]
        return ranked[:n]

    def _all_cash(self, market: MarketView) -> list[TargetWeight]:
        return [TargetWeight("BIL", 1.0)] if market.trailing_return("BIL", 0) is not None else []
