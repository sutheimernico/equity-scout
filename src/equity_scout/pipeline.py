"""Wire the funnel: fetch -> gate -> score -> bucket -> theses -> RunResult."""
from __future__ import annotations

from equity_scout.analysis import AnalysisProvider, attach_theses
from equity_scout.buckets import assign_buckets
from equity_scout.data.fetch import fetch_all
from equity_scout.data.provider import MarketDataProvider
from equity_scout.factors import score_factors
from equity_scout.gate import apply_gate, summarize_gate
from equity_scout.models import Instrument, RunResult


def run_pipeline(
    universe: list[Instrument],
    provider: MarketDataProvider,
    analysis: AnalysisProvider | None = None,
    top_n: int = 10,
    min_metrics: int = 4,
    created_at: str = "",
    max_workers: int = 8,
    llm_top_n: int | None = None,
) -> RunResult:
    quotes = fetch_all(provider, universe, max_workers=max_workers)
    passed, rejected = apply_gate(quotes, min_metrics=min_metrics)
    scores = score_factors(passed)
    buckets = assign_buckets(scores, top_n=top_n)
    buckets = attach_theses(buckets, analysis, max_per_bucket=llm_top_n)
    return RunResult(
        created_at=created_at,
        universe_size=len(universe),
        gated_out=rejected,
        buckets=buckets,
        gate_stats=summarize_gate(rejected, universe),
    )
