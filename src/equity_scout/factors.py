"""Cross-sectional factor scoring. Each metric -> percentile in [0,1] over the set."""
from __future__ import annotations

from equity_scout.models import FactorScore, Quote

# family -> list of (field_name, higher_is_better)
_FAMILIES: dict[str, list[tuple[str, bool]]] = {
    "value": [("trailing_pe", False), ("price_to_book", False)],
    "quality": [("return_on_equity", True), ("profit_margins", True)],
    "momentum": [("momentum_6m", True)],
    "growth": [("revenue_growth", True), ("earnings_growth", True)],
}


def _percentiles(values: dict[str, float], higher_is_better: bool) -> dict[str, float]:
    """Rank-based percentile in [0,1]. Best value -> ~1.0, worst -> 0.0. Single item -> 0.5."""
    if not values:
        return {}
    if len(values) == 1:
        return {k: 0.5 for k in values}
    # order worst-first so the best ends at index n-1 -> percentile 1.0
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=not higher_is_better)
    n = len(ordered)
    return {ticker: idx / (n - 1) for idx, (ticker, _) in enumerate(ordered)}


def score_factors(quotes: list[Quote]) -> list[FactorScore]:
    by_ticker = {q.instrument.ticker: q for q in quotes}
    # family -> ticker -> list of metric percentiles (averaged into the family score)
    family_pcts: dict[str, dict[str, list[float]]] = {f: {} for f in _FAMILIES}
    for family, metrics in _FAMILIES.items():
        for field_name, higher in metrics:
            present = {
                t: getattr(q, field_name)
                for t, q in by_ticker.items()
                if getattr(q, field_name) is not None
            }
            for t, pct in _percentiles(present, higher).items():
                family_pcts[family].setdefault(t, []).append(pct)

    scores: list[FactorScore] = []
    for t, q in by_ticker.items():
        def fam(name: str, _t: str = t) -> float:
            vals = family_pcts[name].get(_t, [])
            return sum(vals) / len(vals) if vals else 0.0

        scores.append(
            FactorScore(instrument=q.instrument, value=fam("value"),
                        quality=fam("quality"), momentum=fam("momentum"),
                        growth=fam("growth"))
        )
    return scores
