"""Risk buckets by character — each stock lands in exactly ONE bucket.

The old design ranked every stock by each bucket's weighted composite and took the top-N, so a
rounded-good stock (high quality AND momentum) showed up in all three buckets, only re-sorted. That
is not the idea: "defensive" should hold genuinely defensive stocks, "aggressive" genuinely offensive
ones. So we first assign each stock to a character group by its *tilt* (offensive factors minus
defensive factors) via terciles — disjoint by construction — then rank within the group by that
bucket's composite so the best fits surface first.
"""
from __future__ import annotations

from equity_scout.models import FactorScore, Pick

BUCKET_WEIGHTS: dict[str, dict[str, float]] = {
    "defensive": {"value": 0.30, "quality": 0.35, "momentum": 0.05, "growth": 0.05, "low_vol": 0.25},
    "balanced": {"value": 0.20, "quality": 0.20, "momentum": 0.20, "growth": 0.20, "low_vol": 0.20},
    "aggressive": {"value": 0.10, "quality": 0.10, "momentum": 0.40, "growth": 0.35, "low_vol": 0.05},
}


def _composite(score: FactorScore, weights: dict[str, float]) -> float:
    return (
        weights["value"] * score.value
        + weights["quality"] * score.quality
        + weights["momentum"] * score.momentum
        + weights["growth"] * score.growth
        + weights["low_vol"] * score.low_vol
    )


def _tilt(score: FactorScore) -> float:
    """Offensive lean minus defensive lean. Low → defensive character, high → aggressive."""
    offensive = (score.momentum + score.growth) / 2.0
    defensive = (score.value + score.quality + score.low_vol) / 3.0
    return offensive - defensive


def assign_buckets(scores: list[FactorScore], top_n: int = 10) -> dict[str, list[Pick]]:
    buckets: dict[str, list[Pick]] = {name: [] for name in BUCKET_WEIGHTS}
    if not scores:
        return buckets

    # Disjoint character assignment: split the universe into tilt terciles.
    by_tilt = sorted(scores, key=_tilt)  # ascending → most defensive first
    n = len(by_tilt)
    cut_low, cut_high = n // 3, 2 * n // 3
    members = {
        "defensive": by_tilt[:cut_low],
        "balanced": by_tilt[cut_low:cut_high],
        "aggressive": by_tilt[cut_high:],
    }

    for bucket_name, weights in BUCKET_WEIGHTS.items():
        ranked = sorted(members[bucket_name], key=lambda s: _composite(s, weights), reverse=True)
        buckets[bucket_name] = [
            Pick(
                instrument=score.instrument,
                bucket=bucket_name,
                rank=rank,
                composite=_composite(score, weights),
                breakdown={"value": score.value, "quality": score.quality,
                           "momentum": score.momentum, "growth": score.growth,
                           "low_vol": score.low_vol},
            )
            for rank, score in enumerate(ranked[:top_n], start=1)
        ]
    return buckets
