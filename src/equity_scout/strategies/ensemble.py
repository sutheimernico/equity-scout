"""Multi-strategy blend: average the target weights of several component strategies.

The honest answer to "which strategy is best?" is *don't bet on one* — diversify across uncorrelated
strategy types (broad allocation + trend/crash-switch + risk-scaling). Equal weights on purpose: no
in-sample optimisation of the blend (DeMiguel et al. 2009 show 1/N is a stubbornly strong combiner).
Because each component returns weights summing to <= 1, the blend does too; the engine normalises.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.strategies.base import Strategy, TargetWeight, normalise_weights

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


class EnsembleStrategy:
    def __init__(
        self,
        components: list[Strategy],
        weights: list[float] | None = None,
        name: str = "Multi-Strategie-Mix",
    ) -> None:
        if weights is None:
            weights = [1.0 / len(components)] * len(components)
        if len(weights) != len(components):
            raise ValueError("weights must match components")
        self.components = components
        self.weights = weights
        self.name = name

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        blended: dict[str, float] = {}
        for strategy, weight in zip(self.components, self.weights):
            for target in normalise_weights(strategy.decide(as_of, market)):
                blended[target.ticker] = blended.get(target.ticker, 0.0) + weight * target.weight
        return [TargetWeight(ticker, w) for ticker, w in blended.items() if w > 1e-9]
