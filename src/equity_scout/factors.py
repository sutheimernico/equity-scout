"""Cross-sectional factor scoring.

Each metric becomes a percentile in [0,1]. Two refinements over a naive rank:
- Invalid values are dropped before ranking. A non-positive P/E or P/B is NOT "cheap" — it usually
  means losses or negative equity — so we treat it as missing rather than top-of-value.
- value/quality/growth are ranked WITHIN sector (a tech P/E is not comparable to a utility's);
  momentum and low-vol are ranked globally. Rank-based scoring is ordinal, so it needs no
  winsorizing — an outlier's magnitude doesn't move its rank.
"""
from __future__ import annotations

from equity_scout.models import FactorScore, Quote

# family -> list of (field_name, higher_is_better, require_positive)
_FAMILIES: dict[str, list[tuple[str, bool, bool]]] = {
    "value": [("trailing_pe", False, True), ("price_to_book", False, True)],
    "quality": [("return_on_equity", True, False), ("profit_margins", True, False)],
    "momentum": [("momentum_6m", True, False)],
    "growth": [("revenue_growth", True, False), ("earnings_growth", True, False)],
    "low_vol": [("volatility_6m", False, False)],  # lower volatility ranks higher
}
# Families ranked within sector (others rank globally).
_SECTOR_RELATIVE = {"value", "quality", "growth"}


def _clean(value: float | None, require_positive: bool) -> float | None:
    if value is None:
        return None
    if require_positive and value <= 0:
        return None
    return value


def _percentiles(values: dict[str, float], higher_is_better: bool) -> dict[str, float]:
    """Rank-based percentile in [0,1]. Best value -> ~1.0, worst -> 0.0. Single item -> 0.5."""
    if not values:
        return {}
    if len(values) == 1:
        return {k: 0.5 for k in values}
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=not higher_is_better)
    n = len(ordered)
    return {ticker: idx / (n - 1) for idx, (ticker, _) in enumerate(ordered)}


def _rank_metric(
    present: dict[str, float], higher: bool, sector_of: dict[str, str], sector_relative: bool
) -> dict[str, float]:
    """Percentiles for one metric, globally or within each sector group."""
    if not sector_relative:
        return _percentiles(present, higher)
    groups: dict[str, dict[str, float]] = {}
    for ticker, value in present.items():
        groups.setdefault(sector_of[ticker], {})[ticker] = value
    out: dict[str, float] = {}
    for group in groups.values():
        out.update(_percentiles(group, higher))
    return out


def score_factors(quotes: list[Quote]) -> list[FactorScore]:
    by_ticker = {q.instrument.ticker: q for q in quotes}
    sector_of = {t: q.instrument.sector for t, q in by_ticker.items()}
    family_pcts: dict[str, dict[str, list[float]]] = {f: {} for f in _FAMILIES}

    for family, metrics in _FAMILIES.items():
        sector_relative = family in _SECTOR_RELATIVE
        for field_name, higher, require_positive in metrics:
            present = {
                t: _clean(getattr(q, field_name), require_positive)
                for t, q in by_ticker.items()
            }
            present = {t: v for t, v in present.items() if v is not None}
            for t, pct in _rank_metric(present, higher, sector_of, sector_relative).items():
                family_pcts[family].setdefault(t, []).append(pct)

    scores: list[FactorScore] = []
    for t, q in by_ticker.items():
        def fam(name: str, _t: str = t) -> float:
            vals = family_pcts[name].get(_t, [])
            return sum(vals) / len(vals) if vals else 0.0

        scores.append(
            FactorScore(instrument=q.instrument, value=fam("value"),
                        quality=fam("quality"), momentum=fam("momentum"),
                        growth=fam("growth"), low_vol=fam("low_vol"))
        )
    return scores
