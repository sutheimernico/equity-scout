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
    """A single target allocation: hold `weight` (fraction of equity) in `ticker`.

    `side="short"` marks a short exposure of that magnitude — downstream (weights_dict, the
    engine, forward paper) it becomes a NEGATIVE signed weight. `weight` itself stays the
    magnitude in [0, 1] so no strategy can smuggle leverage in via a sign trick."""

    ticker: str
    weight: float
    side: str = "long"

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError(f"weight must be in [0, 1], got {self.weight} for {self.ticker}")
        if self.side not in ("long", "short"):
            raise ValueError(f"side must be 'long' or 'short', got {self.side!r}")

    @property
    def signed_weight(self) -> float:
        return self.weight if self.side == "long" else -self.weight


class Strategy(Protocol):
    name: str

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        """Target weights; sum <= 1, remainder is cash. Must not read data >= as_of."""
        ...


def weights_dict(weights: list[TargetWeight]) -> dict[str, float]:
    """Collapse a target list to {ticker: SIGNED weight} (short = negative), summing any
    duplicate tickers — a long and a short on the same ticker net out."""
    out: dict[str, float] = {}
    for tw in weights:
        out[tw.ticker] = out.get(tw.ticker, 0.0) + tw.signed_weight
    return out


def turnover(old: dict[str, float], new: dict[str, float]) -> float:
    """One-way turnover Σ|Δweight| between two SIGNED weight dicts — the cost base for a
    rebalance (flipping a long into a short trades both legs, which |Δ| captures). Shared by the
    backtest engine and forward paper trading so the cost convention can't drift."""
    return sum(abs(new.get(t, 0.0) - old.get(t, 0.0)) for t in set(old) | set(new))


def normalise_weights(weights: list[TargetWeight]) -> list[TargetWeight]:
    """Defensive guard the engine applies to any strategy output: drop zero net weights and scale
    down proportionally if GROSS exposure Σ|w| exceeds 1 (never lever up implicitly — a 0.8 long
    plus 0.8 short book is 1.6x gross and gets scaled to 1.0x)."""
    collapsed = {t: w for t, w in weights_dict(weights).items() if w != 0}
    gross = sum(abs(w) for w in collapsed.values())
    if gross > 1.0:
        collapsed = {t: w / gross for t, w in collapsed.items()}
    return [
        TargetWeight(t, abs(w), side="long" if w > 0 else "short")
        for t, w in collapsed.items()
    ]
