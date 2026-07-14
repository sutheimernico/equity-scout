"""Cross-sectional factor scoring.

Each metric becomes a percentile in [0,1]. Two refinements over a naive rank:
- Invalid values are dropped before ranking. A non-positive P/E or P/B is NOT "cheap" — it usually
  means losses or negative equity — so we treat it as missing rather than top-of-value.
- value/quality/growth are ranked WITHIN sector (a tech P/E is not comparable to a utility's);
  momentum and low-vol are ranked globally. Rank-based scoring is ordinal, so it needs no
  winsorizing — an outlier's magnitude doesn't move its rank.
"""
from __future__ import annotations

import math

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
    # yfinance .info is untyped JSON: across thousands of exotic listings, numeric fields
    # occasionally arrive as strings ("Infinity", "N/A") or bools — anything non-numeric is an
    # honest None, never coerced (live crash on the first 6.6k-universe run, 2026-07-14).
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    if require_positive and value <= 0:
        return None
    return float(value)


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


def _family_score(family_percentiles: dict[str, list[float]], ticker: str) -> float:
    """Mean of a ticker's available metric percentiles in one family; 0.0 if it has none."""
    percentiles = family_percentiles.get(ticker, [])
    return sum(percentiles) / len(percentiles) if percentiles else 0.0


def score_factors(quotes: list[Quote]) -> list[FactorScore]:
    quotes_by_ticker = {quote.instrument.ticker: quote for quote in quotes}
    sector_by_ticker = {ticker: q.instrument.sector for ticker, q in quotes_by_ticker.items()}
    # family -> ticker -> list of that family's metric percentiles (averaged into the family score)
    percentiles_by_family: dict[str, dict[str, list[float]]] = {family: {} for family in _FAMILIES}

    for family, metrics in _FAMILIES.items():
        sector_relative = family in _SECTOR_RELATIVE
        for field_name, higher_is_better, require_positive in metrics:
            present_values = {
                ticker: cleaned
                for ticker, quote in quotes_by_ticker.items()
                if (cleaned := _clean(getattr(quote, field_name), require_positive)) is not None
            }
            ranked = _rank_metric(present_values, higher_is_better, sector_by_ticker, sector_relative)
            for ticker, percentile in ranked.items():
                percentiles_by_family[family].setdefault(ticker, []).append(percentile)

    scores: list[FactorScore] = []
    for ticker, quote in quotes_by_ticker.items():
        scores.append(
            FactorScore(
                instrument=quote.instrument,
                value=_family_score(percentiles_by_family["value"], ticker),
                quality=_family_score(percentiles_by_family["quality"], ticker),
                momentum=_family_score(percentiles_by_family["momentum"], ticker),
                growth=_family_score(percentiles_by_family["growth"], ticker),
                low_vol=_family_score(percentiles_by_family["low_vol"], ticker),
            )
        )
    return scores
