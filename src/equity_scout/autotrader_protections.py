"""Composable risk protections for the Auto-Depot (vision v10).

Freqtrade/LEAN pattern: allocation decides WHAT to hold, a chain of small, independently
testable protections decides HOW MUCH risk to allow — applied in order to the aggregated
target weights, each returning the transformed weights plus an optional `RiskEvent` that is
persisted and surfaced (digest, API, dashboard). Nothing here ever levers UP; protections
only ever move exposure toward cash.

Chain order (spec v10 §2): ConcentrationCap -> RegimeGate -> VolTarget -> DrawdownBreaker.
The breaker is stateful (stage + hysteresis + cooldown); its state lives in the account row
and travels through the mutable `RiskContext`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from equity_scout.market import TRADING_DAYS_PER_YEAR


@dataclass(frozen=True)
class RiskEvent:
    """One intervention booked by a protection — the audit trail for why the book got smaller."""

    protection: str
    action: str  # short machine-readable, e.g. "scale_0.50"
    detail: str  # German, human-readable (digest/dashboard)


@dataclass(frozen=True)
class BreakerState:
    """DrawdownBreaker stage machine: 0 = normal, 1 = half exposure, 2 = flat (cash).
    `changed_at` is the ISO date of the last stage move; every move (up or down) restarts
    the cooldown before the next recovery step."""

    stage: int = 0
    changed_at: str | None = None


@dataclass
class RiskContext:
    """Mutable per-advance context the protections read (and the breaker writes back to)."""

    as_of: pd.Timestamp
    regime_level: str | None = None  # "green"|"yellow"|"red"|"unknown"|None
    depot_returns: pd.Series | None = None  # the depot's own daily return history
    drawdown: float | None = None  # current drawdown from peak equity, >= 0
    breaker: BreakerState = BreakerState()


class ProtectionRule(Protocol):
    name: str

    def apply(
        self, weights: dict[str, float], ctx: RiskContext
    ) -> tuple[dict[str, float], RiskEvent | None]: ...


def _scale(weights: dict[str, float], factor: float) -> dict[str, float]:
    return {t: w * factor for t, w in weights.items()}


@dataclass(frozen=True)
class ConcentrationCap:
    """No single name may exceed `cap` of equity (absolute, so shorts count too). Clipped
    mass becomes cash — never redistributed, same honesty as ml_bot._confidence_weights."""

    cap: float = 0.10
    name: str = "concentration_cap"

    def apply(
        self, weights: dict[str, float], ctx: RiskContext
    ) -> tuple[dict[str, float], RiskEvent | None]:
        clipped = {
            t: math.copysign(self.cap, w) if abs(w) > self.cap else w for t, w in weights.items()
        }
        offenders = sorted(t for t in weights if abs(weights[t]) > self.cap + 1e-12)
        if not offenders:
            return weights, None
        return clipped, RiskEvent(
            protection=self.name,
            action=f"cap_{self.cap:.2f}",
            detail=f"Einzeltitel-Limit {self.cap:.0%} griff bei: {', '.join(offenders)}",
        )


@dataclass(frozen=True)
class RegimeGate:
    """Red regime light -> gross exposure halved. Yellow/green/unknown: no action — an
    unknown regime must never punish the book (honesty rule, mirrors regime.combine)."""

    red_factor: float = 0.5
    name: str = "regime_gate"

    def apply(
        self, weights: dict[str, float], ctx: RiskContext
    ) -> tuple[dict[str, float], RiskEvent | None]:
        if ctx.regime_level != "red" or not weights:
            return weights, None
        return _scale(weights, self.red_factor), RiskEvent(
            protection=self.name,
            action=f"scale_{self.red_factor:.2f}",
            detail=f"Markt-Ampel ROT — Exposure auf {self.red_factor:.0%} reduziert",
        )


@dataclass(frozen=True)
class VolTarget:
    """Scale exposure down to a target annualised depot vol (Moreira & Muir 2017). Never
    scales up (no leverage). Inactive until the depot has `window` + 1 own return points —
    a vol estimate from less history would be noise, so the protection honestly waits."""

    target: float = 0.12
    window: int = 20
    name: str = "vol_target"

    def apply(
        self, weights: dict[str, float], ctx: RiskContext
    ) -> tuple[dict[str, float], RiskEvent | None]:
        returns = ctx.depot_returns
        if returns is None or len(returns) < self.window + 1 or not weights:
            return weights, None
        recent = returns.iloc[-self.window:]
        vol = float(recent.std(ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)
        if not math.isfinite(vol) or vol <= self.target:
            return weights, None
        factor = self.target / vol
        return _scale(weights, factor), RiskEvent(
            protection=self.name,
            action=f"scale_{factor:.2f}",
            detail=(
                f"Depot-Vol {vol:.1%} über Ziel {self.target:.0%} — "
                f"Exposure auf {factor:.0%} skaliert"
            ),
        )


@dataclass(frozen=True)
class DrawdownBreaker:
    """Tiered circuit breaker with hysteresis: drawdown >= soft -> half exposure, >= hard ->
    flat to cash. Recovery one stage at a time, only after `cooldown_days` calendar days
    (~2 weeks =~ 10 trading days) AND drawdown back below the recovery threshold. Escalation
    is immediate — protection must never wait for a cooldown to cut risk."""

    soft: float = 0.10
    hard: float = 0.20
    recover_soft: float = 0.08
    recover_hard: float = 0.15
    cooldown_days: int = 14  # calendar days
    name: str = "drawdown_breaker"

    def _next_stage(self, ctx: RiskContext) -> int:
        dd = ctx.drawdown
        stage = ctx.breaker.stage
        if dd is None:
            return stage
        if dd >= self.hard:
            return 2
        if dd >= self.soft and stage < 1:
            return 1
        cooled = (
            ctx.breaker.changed_at is None
            or (ctx.as_of - pd.Timestamp(ctx.breaker.changed_at)).days >= self.cooldown_days
        )
        if not cooled:
            return stage
        if stage == 2 and dd < self.recover_hard:
            return 1
        if stage == 1 and dd < self.recover_soft:
            return 0
        return stage

    def apply(
        self, weights: dict[str, float], ctx: RiskContext
    ) -> tuple[dict[str, float], RiskEvent | None]:
        old = ctx.breaker.stage
        stage = self._next_stage(ctx)
        if stage != old:
            ctx.breaker = BreakerState(stage=stage, changed_at=ctx.as_of.date().isoformat())
        factor = {0: 1.0, 1: 0.5, 2: 0.0}[stage]
        out = _scale(weights, factor) if factor < 1.0 else weights
        if stage == old:
            return out, None  # a persisting stage acts silently; the stage itself is surfaced
        labels = {0: "normal", 1: "halbes Exposure", 2: "komplett Cash"}
        dd_txt = f"{ctx.drawdown:.1%}" if ctx.drawdown is not None else "n/a"
        return out, RiskEvent(
            protection=self.name,
            action=f"stage_{stage}",
            detail=f"Drawdown {dd_txt}: Stufe {old} → {stage} ({labels[stage]})",
        )


def default_protections() -> list[ProtectionRule]:
    return [ConcentrationCap(), RegimeGate(), VolTarget(), DrawdownBreaker()]


def apply_protections(
    weights: dict[str, float], protections: list[ProtectionRule], ctx: RiskContext
) -> tuple[dict[str, float], list[RiskEvent]]:
    events: list[RiskEvent] = []
    for protection in protections:
        weights, event = protection.apply(weights, ctx)
        if event is not None:
            events.append(event)
    return weights, events
