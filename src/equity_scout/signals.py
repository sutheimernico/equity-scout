"""Entry sub-signals: transparent, rule-based scores in [0, 1] with readable reasons.

Pure functions over already-computed funnel artifacts (the Pick's factor-percentile
breakdown + the EntryPlan reference levels). No network. `breakdown` is passed as a
plain dict so both live `Pick.breakdown` and JSON-round-tripped stored runs work.

The composite here is a static weighted mean — a documented placeholder that the ML
layer (Phase 4) replaces. The sub-signals themselves stay rule-based forever: they are
the explainable part, and style attribution depends on them.

Framing: readings measure entry-PRICE attractiveness of an already-vetted stock.
They are reference information, not buy recommendations (same stance as entry.py).
"""
from __future__ import annotations

from dataclasses import dataclass

from equity_scout.entry import EntryPlan, sma

# A -30% drawdown (or deeper) counts as a "full" dip; shallower dips scale linearly.
_FULL_DIP_DRAWDOWN = 0.30


@dataclass(frozen=True)
class SignalReading:
    name: str  # "dip_quality" | "value_gap" | "momentum"
    score: float  # [0, 1]
    reason: str  # user-facing, German (ADR 0001)


def dip_quality(breakdown: dict[str, float], plan: EntryPlan) -> SignalReading:
    """Meaningful pullback in a fundamentally strong stock.

    depth  = drawdown from the 52w high, saturating at -30%
    score  = depth x quality percentile (no quality data -> 0, honestly)
    """
    quality = float(breakdown.get("quality", 0.0))
    depth = min(max(-plan.drawdown_from_high, 0.0) / _FULL_DIP_DRAWDOWN, 1.0)
    score = round(depth * quality, 4)
    reason = (
        f"Kurs {plan.drawdown_from_high * 100:+.1f} % vom 52-Wochen-Hoch; "
        f"Qualitäts-Perzentil im Funnel: {quality * 100:.0f}."
    )
    return SignalReading("dip_quality", score, reason)


# A 20% discount to the 200-day SMA counts as a "full" value gap.
_FULL_GAP_DISCOUNT = 0.20


def value_gap(breakdown: dict[str, float], plan: EntryPlan) -> SignalReading:
    """Price notably below the long-term anchor in a stock the funnel ranks cheap.

    Only fires below the 200-day SMA — above it there is no gap by definition.
    score = value percentile x (0.3 + 0.7 x discount), discount saturating at -20%.
    The 0.3 floor keeps 'just crossed under the anchor' from scoring zero.
    """
    value = float(breakdown.get("value", 0.0))
    if plan.sma200 is None or plan.sma200 <= 0:
        return SignalReading(
            "value_gap", 0.0, "Kein 200-Tage-Schnitt verfügbar (zu wenig Kurshistorie)."
        )
    rel = plan.price / plan.sma200 - 1.0
    if rel > 0:
        return SignalReading(
            "value_gap",
            0.0,
            f"Kurs {rel * 100:+.1f} % über dem 200-Tage-Schnitt — keine Bewertungslücke.",
        )
    discount = min(-rel / _FULL_GAP_DISCOUNT, 1.0)
    score = round(value * (0.3 + 0.7 * discount), 4)
    reason = (
        f"Kurs {rel * 100:+.1f} % unter dem 200-Tage-Schnitt; "
        f"Value-Perzentil im Funnel: {value * 100:.0f}."
    )
    return SignalReading("value_gap", score, reason)


# Falling knives keep a fraction of their momentum score, not zero: the funnel's 6m
# momentum percentile still carries information; the stabilization filter dampens it.
_KNIFE_DAMPING = 0.3


def momentum(
    breakdown: dict[str, float], plan: EntryPlan, closes: list[float]
) -> SignalReading:
    """Trend filter against catching falling knives.

    Uses the funnel's 6m momentum percentile, damped to 30% while the price still
    sits below its 20-day SMA (i.e. the dip has not stabilized yet).
    """
    mom = float(breakdown.get("momentum", 0.0))
    sma20 = sma(closes, window=20)
    stabilized = sma20 is not None and plan.price >= sma20
    if stabilized:
        score = round(mom, 4)
        reason = (
            f"Kurs auf/über dem 20-Tage-Schnitt (stabilisiert); "
            f"Momentum-Perzentil im Funnel: {mom * 100:.0f}."
        )
    else:
        score = round(mom * _KNIFE_DAMPING, 4)
        reason = (
            f"Kurs unter dem 20-Tage-Schnitt — fällt weiter (fallendes Messer); "
            f"Momentum-Perzentil {mom * 100:.0f} wird gedämpft."
        )
    return SignalReading("momentum", score, reason)


# Static combiner weights — PLACEHOLDER until the ML layer (Phase 4) learns the
# weighting. Dip-quality leads: "quality at a discount" is the copilot's core style.
_COMPOSITE_WEIGHTS = {"dip_quality": 0.40, "value_gap": 0.35, "momentum": 0.25}


def composite_score(readings: list[SignalReading]) -> float:
    """Weighted sum of known sub-signals in [0, 1]; a missing sub-signal contributes 0.
    Unknown names are ignored."""
    return round(
        sum(_COMPOSITE_WEIGHTS[r.name] * r.score for r in readings if r.name in _COMPOSITE_WEIGHTS),
        4,
    )
