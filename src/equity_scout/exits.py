"""Shared exit-rule threshold logic (spec §7 v1 rules): profit target, stop loss, max holding
period. Used by both the arena lanes (lanes.py, Position-based) and the forward paper bots
(forward_paper.py, weight-based) so the two exit mechanisms can't silently drift apart.

Pure function, no I/O: given the return realised since entry and the holding period, decide
whether to exit and why. It has no notion of shares, prices, or portfolios — callers own how they
compute the return (sign-adjusted for short, where that applies) and the holding period for their
own position representation.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExitRules:
    """v1 exit rules (spec §7): deliberately simple and identical everywhere they apply."""

    profit_target: float = 0.20  # exit once the return clears +target
    stop_loss: float = 0.15  # exit once the return breaches -stop
    max_holding_days: int = 180  # exit once held longer than this


def exit_reason(return_pct: float, held_days: int, rules: ExitRules) -> str | None:
    """German exit reason for (return since entry, days held), or None to keep holding.

    Boundaries are exclusive (`>`/`<`): exactly +20% return or exactly 180 days held is NOT yet an
    exit — matches the pre-existing lanes.py semantics this was extracted from.
    """
    if return_pct > rules.profit_target:
        return f"Kursziel erreicht (+{rules.profit_target * 100:.0f} %)"
    if return_pct < -rules.stop_loss:
        return f"Stop-Loss ausgelöst (−{rules.stop_loss * 100:.0f} %)"
    if held_days > rules.max_holding_days:
        return f"Maximale Haltedauer überschritten ({rules.max_holding_days} Tage)"
    return None
