"""Per-bet self-analysis of the meta-model: which out-of-sample calls were wrong, and in what regime.

Turns the raw `BetRecord` list into something honest to look at — not just "69% hit rate" but *where*
the misses cluster. The regime contrast (mean feature value on correct vs. wrong calls) is the useful
part: it shows the conditions under which the model should be trusted less.
"""
from __future__ import annotations

from equity_scout.ml.meta_model import BetRecord


def attribution_summary(bets: list[BetRecord], *, top_n: int = 8) -> dict:
    if not bets:
        return {"n_bets": 0, "n_errors": 0, "hit_rate": 0.0, "worst": [], "regime_contrast": {}}

    errors = [b for b in bets if not b.correct]
    correct = [b for b in bets if b.correct]
    feature_names = list(bets[0].features.keys())

    def mean_feature(group: list[BetRecord], feature: str) -> float | None:
        return round(sum(b.features[feature] for b in group) / len(group), 4) if group else None

    regime_contrast = {
        feature: {"correct": mean_feature(correct, feature), "wrong": mean_feature(errors, feature)}
        for feature in feature_names
    }
    # Most overconfident mistakes first — a confident wrong call is the most instructive.
    worst = sorted(errors, key=lambda b: abs(b.probability - 0.5), reverse=True)[:top_n]

    return {
        "n_bets": len(bets),
        "n_errors": len(errors),
        "hit_rate": round(len(correct) / len(bets), 3),
        "worst": [
            {
                "date": b.date,
                "decision": b.decision,
                "probability": b.probability,
                "label": b.label,
                "features": b.features,
            }
            for b in worst
        ],
        "regime_contrast": regime_contrast,
    }
