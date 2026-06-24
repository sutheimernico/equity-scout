"""Domain models. All frozen — a run produces immutable snapshots."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Instrument:
    ticker: str
    name: str
    exchange: str
    region: str
    currency: str
    sector: str


@dataclass(frozen=True)
class Quote:
    """Raw metrics for one instrument. None means 'not available from the source'."""

    instrument: Instrument
    trailing_pe: float | None
    price_to_book: float | None
    return_on_equity: float | None
    profit_margins: float | None
    revenue_growth: float | None
    earnings_growth: float | None
    momentum_6m: float | None  # 6-month total return, computed from price history


@dataclass(frozen=True)
class FactorScore:
    """Percentile scores in [0, 1] per factor family."""

    instrument: Instrument
    value: float
    quality: float
    momentum: float
    growth: float


@dataclass(frozen=True)
class Pick:
    instrument: Instrument
    bucket: str
    rank: int
    composite: float
    breakdown: dict[str, float]  # family -> percentile
    thesis: str | None = None


@dataclass(frozen=True)
class RunResult:
    created_at: str  # ISO 8601, injected by caller (no Date.now in pure code paths)
    universe_size: int
    gated_out: dict[str, str]  # ticker -> rejection reason
    buckets: dict[str, list[Pick]] = field(default_factory=dict)
