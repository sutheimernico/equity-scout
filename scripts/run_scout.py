"""CLI: run the funnel, persist a snapshot, print a summary.

Default provider is 'fake' for a deterministic offline run; pass --provider yfinance for live.
yfinance is wrapped in a read-through cache by default (--no-cache to disable).
LLM theses off by default (--use-llm to enable).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from equity_scout.analysis import ClaudeCliAnalysis, FakeAnalysis
from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_UNIVERSE_PATH, DISCLAIMER
from equity_scout.data.cache import CachedProvider, QuoteCache
from equity_scout.data.fake_provider import FakeProvider
from equity_scout.data.news import YFinanceNews
from equity_scout.data.yf_provider import FetchStats, YFinanceProvider
from equity_scout.data.universe_storage import load_instrument_meta, upsert_instrument_meta
from equity_scout.pipeline import run_pipeline
from equity_scout.storage import init_db, save_run, save_run_scores
from equity_scout.universe import apply_meta_overlay, load_universe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=DEFAULT_UNIVERSE_PATH)
    ap.add_argument("--db", default=DEFAULT_DB_PATH)
    ap.add_argument("--cache-db", default="equity_scout_cache.db")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--cache-max-age", type=int, default=1,
                    help="Serve cached quotes up to N days old (the scheduled weekly run uses 7 "
                         "so the nightly prefetch warm-up is actually used).")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--max-workers", type=int, default=4, help="Bounded parallel fetch (1 = serial).")
    ap.add_argument("--provider", choices=["fake", "yfinance"], default="fake")
    ap.add_argument("--use-llm", action="store_true")
    ap.add_argument("--llm-top-n", type=int, default=3,
                    help="Cap LLM theses to top-N per bucket (cost control).")
    ap.add_argument("--no-news", action="store_true", help="Skip fetching recent headlines.")
    ap.add_argument("--news-top-n", type=int, default=5,
                    help="Fetch headlines for top-N picks per bucket (yfinance only).")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    universe = apply_meta_overlay(load_universe(args.universe), load_instrument_meta(args.db))
    fetch_stats = FetchStats() if args.provider == "yfinance" else None
    base = YFinanceProvider(stats=fetch_stats) if args.provider == "yfinance" else FakeProvider()
    if args.provider == "yfinance" and not args.no_cache:
        provider = CachedProvider(base, QuoteCache(args.cache_db),
                                  run_date=now.date().isoformat(),
                                  max_age_days=args.cache_max_age)
    else:
        provider = base

    def _persist_sectors(sectors: dict[str, str]) -> None:
        upsert_instrument_meta(args.db, sectors, source="yfinance.info",
                               updated_at=now.date().isoformat())
    analysis = ClaudeCliAnalysis() if args.use_llm else FakeAnalysis()
    # Headlines only make sense with live data; fake provider stays fully offline.
    news = None if (args.no_news or args.provider != "yfinance") else YFinanceNews()

    full_ranking: dict = {}
    run = run_pipeline(
        universe, provider, analysis=analysis, top_n=args.top_n,
        created_at=now.isoformat(timespec="seconds"), max_workers=args.max_workers,
        llm_top_n=args.llm_top_n, news=news, news_top_n=args.news_top_n,
        fetch_stats=fetch_stats, sector_sink=_persist_sectors,
        ranking_sink=full_ranking.update,
    )
    init_db(args.db)
    run_id = save_run(args.db, run)
    save_run_scores(args.db, run_id, full_ranking)

    print(f"\nRun {run.created_at} — universe {run.universe_size}, gated out {len(run.gated_out)}")
    dq = run.data_quality
    if dq.get("attempted"):
        print(
            f"Data quality: {dq['attempted']} fetched, "
            f"{dq['info_failed']} info-failures, {dq['closes_failed']} price-failures "
            f"(error rate {dq['fetch_error_rate']:.1%})"
        )
    for bucket, picks in run.buckets.items():
        print(f"\n[{bucket}]")
        for p in picks:
            print(f"  {p.rank:>2}. {p.instrument.ticker:<12} score={p.composite:.3f}")
    print(f"\n{DISCLAIMER}\n")


if __name__ == "__main__":
    main()
