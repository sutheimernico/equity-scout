"""The v1 strategy set. One place the CLI and the API both read, so they never drift apart.

Three honest value propositions on display: discipline (DCA), momentum/trend switching (GEM, DAA),
and risk scaling (Vol-Targeting) — each judged against two passive benchmarks (60/40, Permanent
Portfolio) after costs.

v16 adds four families that decide on DIFFERENT grounds than the originals, because twelve
variants of one idea search a narrower space than four unrelated ones: low-vol picks by risk
alone, cross-sectional momentum ranks a wide universe on 12-1, mean reversion buys the losers
these two would sell, and risk parity refuses to select at all. Each starts with an empty
forward track and must earn its way into the depot through the same promotion gate as an arena
lane — none is hand-promoted.
"""
from __future__ import annotations

from equity_scout.strategies.base import Strategy
from equity_scout.strategies.cross_momentum import CrossSectionalMomentumStrategy
from equity_scout.strategies.daa import DefensiveAssetAllocationStrategy
from equity_scout.strategies.dca import DCAStrategy
from equity_scout.strategies.dual_momentum import DualMomentumStrategy
from equity_scout.strategies.ensemble import EnsembleStrategy
from equity_scout.strategies.low_vol import LowVolatilityStrategy
from equity_scout.strategies.mean_reversion import MeanReversionStrategy
from equity_scout.strategies.permanent import PermanentPortfolioStrategy
from equity_scout.strategies.risk_parity import RiskParityStrategy
from equity_scout.strategies.sector_rotation import SectorRotationStrategy
from equity_scout.strategies.sixty_forty import SixtyFortyStrategy
from equity_scout.strategies.vol_target import VolatilityTargetStrategy


def default_strategies() -> list[Strategy]:
    permanent = PermanentPortfolioStrategy()
    vol_target = VolatilityTargetStrategy()
    gem = DualMomentumStrategy()
    daa = DefensiveAssetAllocationStrategy()
    # Equal-weight blend of the uncorrelated strategy types: allocation + risk-scaling + momentum + trend.
    # v8: sector rotation deliberately stays OUT of the blend — changing a running
    # ensemble's composition would rewrite its forward-paper history (C4 lesson).
    # v16: the four new families stay out for exactly the same reason.
    blend = EnsembleStrategy([permanent, vol_target, gem, daa])
    return [
        DCAStrategy(), SixtyFortyStrategy(), permanent, vol_target, gem, daa,
        SectorRotationStrategy(), blend,
        LowVolatilityStrategy(), CrossSectionalMomentumStrategy(),
        MeanReversionStrategy(), RiskParityStrategy(),
    ]
