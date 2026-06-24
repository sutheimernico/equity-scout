"""Global Equities Momentum (GEM) — Antonacci 2012. Dual = relative + absolute momentum.

Relative: pick the stronger of the risky assets (US vs international equity) by trailing return.
Absolute: only hold it if it also beats the cash hurdle (T-bills); otherwise go to bonds. One
position at a time, monthly. The cleanest textbook demonstration of momentum + a crash switch.
Source: Antonacci, "Risk Premia Harvesting Through Dual Momentum" (2012)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


class DualMomentumStrategy:
    name = "Dual Momentum (GEM)"

    def __init__(
        self,
        risk_assets: tuple[str, ...] = ("SPY", "VEU"),
        safe: str = "IEF",
        hurdle: str = "BIL",
        lookback_months: int = 12,
    ) -> None:
        self.risk_assets = risk_assets
        self.safe = safe
        self.hurdle = hurdle
        self.lookback_months = lookback_months

    def _defensive(self, market: MarketView) -> list[TargetWeight]:
        """Go to bonds; if the bond asset has no history (missing/too new), fall back to the cash
        proxy (BIL) rather than guess."""
        target = self.safe if market.trailing_return(self.safe, 0) is not None else self.hurdle
        return [TargetWeight(target, 1.0)]

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        moms: dict[str, float] = {}
        for asset in self.risk_assets:
            mom = market.trailing_return(asset, self.lookback_months)
            if mom is None:  # not enough history yet → sit defensively, never guess
                return self._defensive(market)
            moms[asset] = mom
        hurdle_mom = market.trailing_return(self.hurdle, self.lookback_months)
        if hurdle_mom is None:
            return self._defensive(market)
        best = max(moms, key=lambda asset: moms[asset])  # relative momentum
        if moms[best] > hurdle_mom:  # absolute momentum: must also beat cash
            return [TargetWeight(best, 1.0)]
        return self._defensive(market)
