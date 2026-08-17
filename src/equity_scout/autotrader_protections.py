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
    # VIX-forecast/trailing ratio (vol_forecast.py); None = trailing estimator only
    vol_multiplier: float | None = None


class ProtectionRule(Protocol):
    name: str

    def apply(
        self, weights: dict[str, float], ctx: RiskContext
    ) -> tuple[dict[str, float], RiskEvent | None]: ...


def _scale(weights: dict[str, float], factor: float) -> dict[str, float]:
    return {t: w * factor for t, w in weights.items()}


@dataclass(frozen=True)
class ConcentrationCap:
    """No single name may exceed `cap` of equity (absolute, so shorts count too).

    What happens to the clipped mass is a real economic choice, so it is a parameter:

    - `redistribute=False` (default, and what the live depot has run since 2026-07-16): the
      clipped weight becomes CASH. Conservative and simple, same stance as
      ml_bot._confidence_weights.
    - `redistribute=True`: the clipped weight is spread over the names that are still UNDER
      the cap, proportionally to their own weights and only up to the cap.

    Why the option exists (measured 2026-08-10): with eight sleeves looking through onto a
    shared ETF core, SPY/IEF/VEU all pinned at exactly 10.00% and the depot sat at 60.2% gross
    — 39.8% in cash that no risk rule asked for. The cap's purpose is to limit CONCENTRATION,
    not to hold cash; leaving the freed mass idle turns a diversification rule into a
    de-facto market-timing call and cost measurable return against a rising market.

    The default stays False on purpose: flipping it changes the live depot's behaviour
    mid-track, and that track is the only out-of-sample evidence this project has. Switching
    it is Nico's call and needs a marked regime break, exactly like the crypto lane's
    timescale change.
    """

    cap: float = 0.10
    name: str = "concentration_cap"
    redistribute: bool = False

    def _redistribute(self, clipped: dict[str, float], freed: float) -> dict[str, float]:
        """Spread `freed` over the names still under the cap, proportional to their weight,
        never past the cap. Runs to a fixed point because each pass either places everything
        or fills at least one name to the cap."""
        out = dict(clipped)
        for _ in range(len(out) + 1):
            if freed <= 1e-12:
                break
            room = {t: self.cap - abs(w) for t, w in out.items() if self.cap - abs(w) > 1e-12}
            if not room:
                break  # everything is at the cap — the remainder honestly stays cash
            base = sum(abs(out[t]) for t in room)
            if base <= 1e-12:
                break  # nothing to be proportional to; refuse to invent a distribution
            placed = 0.0
            for ticker, headroom in room.items():
                share = min(freed * abs(out[ticker]) / base, headroom)
                out[ticker] += math.copysign(share, out[ticker])
                placed += share
            if placed <= 1e-12:
                break
            freed -= placed
        return out

    def apply(
        self, weights: dict[str, float], ctx: RiskContext
    ) -> tuple[dict[str, float], RiskEvent | None]:
        clipped = {
            t: math.copysign(self.cap, w) if abs(w) > self.cap else w for t, w in weights.items()
        }
        offenders = sorted(t for t in weights if abs(weights[t]) > self.cap + 1e-12)
        if not offenders:
            return weights, None
        detail = f"Einzeltitel-Limit {self.cap:.0%} griff bei: {', '.join(offenders)}"
        if self.redistribute:
            freed = sum(abs(weights[t]) for t in offenders) - self.cap * len(offenders)
            clipped = self._redistribute(clipped, freed)
            detail += f" — {freed:.1%} auf die übrigen Titel verteilt"
        return clipped, RiskEvent(
            protection=self.name,
            action=f"cap_{self.cap:.2f}" + ("_redistributed" if self.redistribute else ""),
            detail=detail,
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
    a vol estimate from less history would be noise, so the protection honestly waits.

    Estimator since 2026-08-17: the depot's own trailing vol scaled by a VIX-forecast
    multiplier when `ctx.vol_multiplier` is set (study 2026-08-12 — implied vol predicts the
    next 20 days better than the trailing window it replaces), trailing alone whenever the
    VIX leg is missing or implausible. That is a behaviour change on the live depot, so each
    event names its estimator via the `(VIX-Prognose)`/`(trailing)` label in `detail`.
    """

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
        trailing = float(recent.std(ddof=1)) * math.sqrt(TRADING_DAYS_PER_YEAR)
        if not math.isfinite(trailing):
            return weights, None
        multiplier = ctx.vol_multiplier if ctx.vol_multiplier is not None else 1.0
        vol = trailing * multiplier
        if vol <= self.target:
            return weights, None
        factor = self.target / vol
        source = "VIX-Prognose" if ctx.vol_multiplier is not None else "trailing"
        return _scale(weights, factor), RiskEvent(
            protection=self.name,
            action=f"scale_{factor:.2f}",
            detail=(
                f"Depot-Vol ({source}) {vol:.1%} über Ziel {self.target:.0%} — "
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
    """The live chain, in order: cap -> regime -> vol target -> drawdown breaker.

    `redistribute=True` since 2026-08-10, and it is a behaviour change worth stating.
    Measured on that day's real depot: the sleeves asked for 83.9 % gross, SPY aggregated to
    29.1 % and VEU to 14.6 % through the look-through (seven sleeves share one ETF core), the
    cap clipped both to 10 %, and **23.7 percentage points of capital went to cash that no
    risk rule had asked for** — the depot ran at 60.2 % gross against SPY's +3.3 %.

    The cap's job is to bound how much sits in ONE name, not to hold cash. Redistributing the
    clipped mass onto the names still under the cap keeps that bound exactly as strict (no
    position exceeds 10 %) while the book stays invested. The risk layers after it — regime
    gate, vol target, drawdown breaker — still see and scale the full book, so downside
    control is unchanged; only the unintended cash drag is gone.

    This splits the depot's track record in two. The engine stamps `protection_regime` on the
    account the first time it advances under the new rule, and every surface that shows the
    depot curve must treat the segments as separate series (same rule as the crypto lane's
    timescale change and `execution_regime` in the session lane).
    """
    return [ConcentrationCap(redistribute=True), RegimeGate(), VolTarget(), DrawdownBreaker()]


def apply_protections(
    weights: dict[str, float], protections: list[ProtectionRule], ctx: RiskContext
) -> tuple[dict[str, float], list[RiskEvent]]:
    events: list[RiskEvent] = []
    for protection in protections:
        weights, event = protection.apply(weights, ctx)
        if event is not None:
            events.append(event)
    return weights, events
