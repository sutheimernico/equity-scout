"""Strategy seam: the one protocol every paper-trading strategy implements.

`decide` returns target portfolio weights (ticker -> weight in [0, 1]); the sum may be < 1, the
remainder is held as cash. It receives a look-ahead-safe `MarketView` (past only) and the account's
current state, so a strategy is a pure function of (date, visible market, state) and is trivially
testable against synthetic price panels. The same `decide` runs in backtest and in forward paper
trading — there is no second code path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView


@dataclass(frozen=True)
class AccountState:
    """What a strategy may know about its own account when deciding."""

    current_weights: dict[str, float] = field(default_factory=dict)
    step: int = 0  # number of rebalances already done (0 at the first decision)


class Strategy(Protocol):
    name: str

    def decide(
        self, as_of: pd.Timestamp, market: MarketView, state: AccountState
    ) -> dict[str, float]:
        """Target weights; sum <= 1, remainder is cash. Must not read data >= as_of."""
        ...


def clip_weights(weights: dict[str, float]) -> dict[str, float]:
    """Defensive guard the engine applies to any strategy output: drop non-positive weights and
    scale down proportionally if the total exceeds 1 (never lever up implicitly)."""
    positive = {ticker: w for ticker, w in weights.items() if w > 0}
    total = sum(positive.values())
    if total > 1.0:
        return {ticker: w / total for ticker, w in positive.items()}
    return positive
