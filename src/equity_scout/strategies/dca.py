"""Dollar-cost averaging: deploy capital into a target mix in equal tranches over the first N months,
then hold. The education anchor Nico asked for ("tranchenweise einkaufen") — no timing claim.

Honest takeaway the dashboard will show: DCA lowers entry-timing risk but costs expected return (more
time in cash), and over long horizons it converges to lump-sum. State-free: the tranche is derived
from months elapsed since the panel start (= the account's inception), not from carried state."""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


class DCAStrategy:
    name = "DCA (12-month entry)"

    def __init__(self, target: dict[str, float] | None = None, tranches: int = 12) -> None:
        self.target = target or {"SPY": 0.60, "IEF": 0.40}
        self.tranches = tranches

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        start = market.first_date
        if start is None:
            return []  # no data yet → all cash
        months_elapsed = (as_of.year - start.year) * 12 + (as_of.month - start.month)
        invested = min(1.0, (months_elapsed + 1) / self.tranches)  # first tranche on the first rebal
        return [TargetWeight(ticker, weight * invested) for ticker, weight in self.target.items()]
