"""Risk buckets = factor-family weightings. Composite = weighted sum of family percentiles."""
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


def assign_buckets(scores: list[FactorScore], top_n: int = 10) -> dict[str, list[Pick]]:
    buckets: dict[str, list[Pick]] = {}
    for bucket_name, weights in BUCKET_WEIGHTS.items():
        ranked = sorted(scores, key=lambda score: _composite(score, weights), reverse=True)
        picks: list[Pick] = []
        for rank, score in enumerate(ranked[:top_n], start=1):
            picks.append(
                Pick(
                    instrument=score.instrument,
                    bucket=bucket_name,
                    rank=rank,
                    composite=_composite(score, weights),
                    breakdown={"value": score.value, "quality": score.quality,
                               "momentum": score.momentum, "growth": score.growth,
                               "low_vol": score.low_vol},
                )
            )
        buckets[bucket_name] = picks
    return buckets
