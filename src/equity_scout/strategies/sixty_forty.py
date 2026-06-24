"""60/40 — the mandatory passive benchmark: fixed 60% stocks / 40% bonds, rebalanced each period.

Not an "active" strategy; it exists so every active model is judged against the dumbest sensible
diversified portfolio after costs (DeMiguel et al. 2009 show 1/N is a stubborn benchmark)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.strategies.base import AccountState

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


class SixtyFortyStrategy:
    def __init__(self, stock: str = "SPY", bond: str = "IEF", stock_weight: float = 0.60) -> None:
        self.stock = stock
        self.bond = bond
        self.stock_weight = stock_weight
        self.name = f"{int(stock_weight * 100)}/{int((1 - stock_weight) * 100)}"

    def decide(
        self, as_of: pd.Timestamp, market: MarketView, state: AccountState
    ) -> dict[str, float]:
        return {self.stock: self.stock_weight, self.bond: 1.0 - self.stock_weight}
