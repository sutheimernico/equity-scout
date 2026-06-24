"""Risk buckets = factor-family weightings. Composite = weighted sum of family percentiles."""
from __future__ import annotations

from equity_scout.models import FactorScore, Pick

BUCKET_WEIGHTS: dict[str, dict[str, float]] = {
    "defensive": {"value": 0.35, "quality": 0.45, "momentum": 0.10, "growth": 0.10},
    "balanced": {"value": 0.25, "quality": 0.25, "momentum": 0.25, "growth": 0.25},
    "aggressive": {"value": 0.10, "quality": 0.10, "momentum": 0.40, "growth": 0.40},
}


def _composite(score: FactorScore, weights: dict[str, float]) -> float:
    return (
        weights["value"] * score.value
        + weights["quality"] * score.quality
        + weights["momentum"] * score.momentum
        + weights["growth"] * score.growth
    )


def assign_buckets(scores: list[FactorScore], top_n: int = 10) -> dict[str, list[Pick]]:
    out: dict[str, list[Pick]] = {}
    for bucket, weights in BUCKET_WEIGHTS.items():
        ranked = sorted(scores, key=lambda s: _composite(s, weights), reverse=True)
        picks: list[Pick] = []
        for rank, s in enumerate(ranked[:top_n], start=1):
            picks.append(
                Pick(
                    instrument=s.instrument,
                    bucket=bucket,
                    rank=rank,
                    composite=_composite(s, weights),
                    breakdown={"value": s.value, "quality": s.quality,
                               "momentum": s.momentum, "growth": s.growth},
                )
            )
        out[bucket] = picks
    return out
