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
from equity_scout.liquidity import filter_investable
from equity_scout.models import Instrument, Pick, Quote, RunResult


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
    ranking_sink: Callable[[dict[str, list[Pick]]], None] | None = None,
    investable_only: bool = True,
    fx_rate: Callable[[str | None], float | None] | None = None,
) -> RunResult:
    quotes = fetch_all(provider, universe, max_workers=max_workers)
    if sector_sink is not None:
        sector_sink(harvest_sectors(universe, quotes))
    passed, rejected = apply_gate(quotes, min_metrics=min_metrics)
    if investable_only:
        # Zweite Stufe nach der Datenvollständigkeit: Größe und Handelsumsatz. Beide
        # Ablehnungsarten laufen in denselben Bericht, damit im Cockpit sichtbar bleibt,
        # WARUM ein Lauf über 1 200 Titel am Ende 30 zeigt (siehe liquidity.py).
        passed, illiquid = filter_investable(passed, rate=fx_rate)
        rejected = {**rejected, **illiquid}
    scores = score_factors(passed)
    if ranking_sink is not None:
        # Full cross-section for the filter feature; RunResult keeps the top-N slice
        # (ranks are a prefix of the full ranking), so news/LLM cost stays unchanged.
        full_buckets = assign_buckets(scores, top_n=len(scores))
        ranking_sink(full_buckets)
        buckets = {b: picks[:top_n] for b, picks in full_buckets.items()}
    else:
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
