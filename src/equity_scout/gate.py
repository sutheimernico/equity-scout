"""Data completeness gate. Without it the funnel ranks thin-data noise to the top."""
from __future__ import annotations

from equity_scout.models import Quote

_METRIC_FIELDS = (
    "trailing_pe", "price_to_book", "return_on_equity",
    "profit_margins", "revenue_growth", "earnings_growth",
)


def apply_gate(quotes: list[Quote], min_metrics: int = 4) -> tuple[list[Quote], dict[str, str]]:
    """Pass a quote if it has >= min_metrics non-None fundamentals AND momentum_6m present."""
    passed: list[Quote] = []
    rejected: dict[str, str] = {}
    for q in quotes:
        present = sum(getattr(q, f) is not None for f in _METRIC_FIELDS)
        if q.momentum_6m is None:
            rejected[q.instrument.ticker] = "missing price history (no 6m momentum)"
        elif present < min_metrics:
            rejected[q.instrument.ticker] = f"too few fundamentals ({present}/{min_metrics})"
        else:
            passed.append(q)
    return passed, rejected
