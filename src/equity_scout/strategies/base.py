"""Strategy seam: the one protocol every paper-trading strategy implements.

`decide` returns a list of `TargetWeight` (ticker -> target portfolio weight). The weights may sum
to less than 1; the remainder is held as cash. It receives a look-ahead-safe `MarketView` (past
only), so a strategy is a pure function of (date, visible market) and is trivially testable against
synthetic price panels. The same `decide` runs in backtest and in forward paper trading — there is
no second code path.

There is deliberately no account-state parameter: every Phase A strategy decides purely from the
market (60/40 is constant, GEM from momentum). State-dependent strategies (DCA, vol-targeting) are
Phase B — we add the parameter when the first real use case exists, not before (YAGNI).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


@dataclass(frozen=True)
class TargetWeight:
    """A single target allocation: hold `weight` (fraction of equity) in `ticker`."""

    ticker: str
    weight: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight must be in [0, 1], got {self.weight} for {self.ticker}")


class Strategy(Protocol):
    name: str

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        """Target weights; sum <= 1, remainder is cash. Must not read data >= as_of."""
        ...


def weights_dict(weights: list[TargetWeight]) -> dict[str, float]:
    """Collapse a target list to {ticker: weight}, summing any duplicate tickers."""
    out: dict[str, float] = {}
    for tw in weights:
        out[tw.ticker] = out.get(tw.ticker, 0.0) + tw.weight
    return out


def normalise_weights(weights: list[TargetWeight]) -> list[TargetWeight]:
    """Defensive guard the engine applies to any strategy output: drop non-positive weights and
    scale down proportionally if the total exceeds 1 (never lever up implicitly)."""
    collapsed = {t: w for t, w in weights_dict(weights).items() if w > 0}
    total = sum(collapsed.values())
    if total > 1.0:
        collapsed = {t: w / total for t, w in collapsed.items()}
    return [TargetWeight(t, w) for t, w in collapsed.items()]
