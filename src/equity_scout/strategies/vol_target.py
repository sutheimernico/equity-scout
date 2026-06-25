"""Volatility targeting: scale exposure to one risk asset so the book's volatility tracks a target,
capped at 1.0 (no leverage). weight = min(cap, target_vol / realised_vol); the rest is cash.

Demonstrates risk scaling — de-risk when markets get choppy, lean in when calm — and is the honest
precursor to the ML sizing layer (Phase E sizes positions the same way, by conviction). Sources:
Moreira & Muir 2017; Harvey et al. 2018 ('The Impact of Volatility Targeting')."""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


class VolatilityTargetStrategy:
    name = "Volatility Targeting"

    def __init__(
        self,
        risk_asset: str = "SPY",
        target_vol: float = 0.10,
        vol_window_days: int = 63,
        leverage_cap: float = 1.0,
    ) -> None:
        self.risk_asset = risk_asset
        self.target_vol = target_vol
        self.vol_window_days = vol_window_days
        self.leverage_cap = leverage_cap

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        realised = market.realised_vol(self.risk_asset, self.vol_window_days)
        if realised is None or realised <= 0:  # not enough history → stay in cash
            return []
        weight = min(self.leverage_cap, self.target_vol / realised)
        return [TargetWeight(self.risk_asset, weight)]
