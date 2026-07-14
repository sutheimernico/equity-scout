"""Wire the funnel: fetch -> gate -> score -> bucket -> theses -> RunResult."""
from __future__ import annotations

from typing import Callable

from equity_scout.analysis import AnalysisProvider, attach_theses
from equity_scout.buckets import assign_buckets
from equity_scout.data.fetch import fetch_all
from equity_scout.data.news import NewsProvider, attach_news
from equity_scout.data.provider import MarketDataProvider
from equity_scout.data.yf_provider import FetchStats
from equity_scout.data_quality import build_data_quality_report
from equity_scout.factors import score_factors
from equity_scout.gate import apply_gate, summarize_gate
from equity_scout.models import Instrument, Quote, RunResult


def harvest_sectors(universe: list[Instrument], quotes: list[Quote]) -> dict[str, str]:
    """Sectors the fetch discovered for instruments the universe knew as 'Unknown' — the caller
    persists them (pipeline stays DB-free)."""
    unknown = {i.ticker for i in universe if i.sector in ("", "Unknown")}
    return {
        q.instrument.ticker: q.instrument.sector
        for q in quotes
        if q.instrument.ticker in unknown and q.instrument.sector not in ("", "Unknown")
    }


def run_pipeline(
    universe: list[Instrument],
    provider: MarketDataProvider,
    analysis: AnalysisProvider | None = None,
    top_n: int = 10,
    min_metrics: int = 4,
    created_at: str = "",
    max_workers: int = 8,
    llm_top_n: int | None = None,
    news: NewsProvider | None = None,
    news_top_n: int | None = 5,
    fetch_stats: FetchStats | None = None,
    sector_sink: Callable[[dict[str, str]], None] | None = None,
) -> RunResult:
    quotes = fetch_all(provider, universe, max_workers=max_workers)
    if sector_sink is not None:
        sector_sink(harvest_sectors(universe, quotes))
    passed, rejected = apply_gate(quotes, min_metrics=min_metrics)
    scores = score_factors(passed)
    buckets = assign_buckets(scores, top_n=top_n)
    buckets = attach_news(buckets, news, max_per_bucket=news_top_n)
    buckets = attach_theses(buckets, analysis, max_per_bucket=llm_top_n)
    return RunResult(
        created_at=created_at,
        universe_size=len(universe),
        gated_out=rejected,
        buckets=buckets,
        gate_stats=summarize_gate(rejected, universe),
        data_quality=build_data_quality_report(quotes, rejected, fetch_stats),
    )
