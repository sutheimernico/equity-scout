"""The v1 strategy set. One place the CLI and the API both read, so they never drift apart.

Grows phase by phase (Phase B adds DCA, Vol-Targeting, DAA, Permanent Portfolio). 60/40 is the
mandatory passive benchmark every active strategy is judged against after costs.
"""
from __future__ import annotations

from equity_scout.strategies.base import Strategy
from equity_scout.strategies.dual_momentum import DualMomentumStrategy
from equity_scout.strategies.sixty_forty import SixtyFortyStrategy


def default_strategies() -> list[Strategy]:
    return [SixtyFortyStrategy(), DualMomentumStrategy()]
