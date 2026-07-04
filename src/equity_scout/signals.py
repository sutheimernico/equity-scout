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

from equity_scout.entry import EntryPlan

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
