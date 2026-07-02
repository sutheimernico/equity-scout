"""Per-run data-quality report: fetch reliability + fundamental completeness.

Complements `gate.summarize_gate` (why tickers were excluded) with a picture of the raw fetch: how
often the provider gave up after retries — `data/fetch.py` and `data/yf_provider.py` used to swallow
those failures into an empty `Quote` with no visibility at all — and how complete the fundamentals
are across whatever came back, regardless of whether it later passed the gate.
"""
from __future__ import annotations

from equity_scout.data.yf_provider import FetchStats
from equity_scout.models import Quote

_FIELDS = (
    "trailing_pe", "price_to_book", "return_on_equity",
    "profit_margins", "revenue_growth", "earnings_growth", "momentum_6m",
)


def build_data_quality_report(
    quotes: list[Quote], gated_out: dict[str, str], fetch_stats: FetchStats | None = None
) -> dict:
    """`quotes` are ALL fetched quotes for the run, pre-gate. `fetch_stats`, when the provider was
    wired with one (real yfinance runs), gives the exact retry-exhaustion counts; without it (fake
    provider, or an older caller that didn't pass one) the report still carries missing-field and
    gate-filtered counts, just without a separate fetch-error rate.
    """
    stats = fetch_stats.summary() if fetch_stats is not None else {
        "attempted": 0, "info_failed": 0, "closes_failed": 0,
    }
    fetch_failures = stats["info_failed"] + stats["closes_failed"]
    attempted = stats["attempted"]
    missing_fields = {field: sum(1 for q in quotes if getattr(q, field) is None) for field in _FIELDS}
    return {
        "attempted": attempted,
        "info_failed": stats["info_failed"],
        "closes_failed": stats["closes_failed"],
        "fetch_error_rate": (fetch_failures / attempted) if attempted else 0.0,
        "missing_fields": missing_fields,
        "gate_filtered": len(gated_out),
    }
