"""Data completeness gate. Without it the funnel ranks thin-data noise to the top."""
from __future__ import annotations

from equity_scout.models import Instrument, Quote

_METRIC_FIELDS = (
    "trailing_pe", "price_to_book", "return_on_equity",
    "profit_margins", "revenue_growth", "earnings_growth",
)


def apply_gate(quotes: list[Quote], min_metrics: int = 4) -> tuple[list[Quote], dict[str, str]]:
    """Pass a quote if it has >= min_metrics non-None fundamentals AND momentum_6m present."""
    passed: list[Quote] = []
    rejected: dict[str, str] = {}
    for quote in quotes:
        present = sum(getattr(quote, field_name) is not None for field_name in _METRIC_FIELDS)
        if quote.momentum_6m is None:
            rejected[quote.instrument.ticker] = "missing price history (no 6m momentum)"
        elif present < min_metrics:
            rejected[quote.instrument.ticker] = f"too few fundamentals ({present}/{min_metrics})"
        else:
            passed.append(quote)
    return passed, rejected


def summarize_gate(rejected: dict[str, str], universe: list[Instrument]) -> dict:
    """Aggregate gate rejections by reason category and by region for visibility."""
    region_of = {i.ticker: i.region for i in universe}
    by_reason: dict[str, int] = {}
    by_region: dict[str, int] = {}
    for ticker, reason in rejected.items():
        category = reason.split("(")[0].strip()  # drop the count detail in parentheses
        by_reason[category] = by_reason.get(category, 0) + 1
        region = region_of.get(ticker, "Unknown")
        by_region[region] = by_region.get(region, 0) + 1
    return {"total_gated": len(rejected), "by_reason": by_reason, "by_region": by_region}
