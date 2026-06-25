"""Permanent Portfolio (Harry Browne): fixed 25/25/25/25 across stocks / long Treasuries / cash /
gold. A static all-weather benchmark — no timing, no estimation, one quadrant for each macro regime
(prosperity/deflation/recession/inflation). Rebalanced back to target each period. It exists to ask
whether the active timing strategies actually beat a dumb fixed allocation after costs."""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


class PermanentPortfolioStrategy:
    name = "Permanent Portfolio"

    def __init__(self, allocation: dict[str, float] | None = None) -> None:
        self.allocation = allocation or {"SPY": 0.25, "TLT": 0.25, "BIL": 0.25, "GLD": 0.25}

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        return [TargetWeight(ticker, weight) for ticker, weight in self.allocation.items()]
