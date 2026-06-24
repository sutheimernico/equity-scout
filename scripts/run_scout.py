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
from equity_scout.data.yf_provider import YFinanceProvider
from equity_scout.pipeline import run_pipeline
from equity_scout.storage import init_db, save_run
from equity_scout.universe import load_universe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=DEFAULT_UNIVERSE_PATH)
    ap.add_argument("--db", default=DEFAULT_DB_PATH)
    ap.add_argument("--cache-db", default="equity_scout_cache.db")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--max-workers", type=int, default=8, help="Bounded parallel fetch (1 = serial).")
    ap.add_argument("--provider", choices=["fake", "yfinance"], default="fake")
    ap.add_argument("--use-llm", action="store_true")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    universe = load_universe(args.universe)
    base = YFinanceProvider() if args.provider == "yfinance" else FakeProvider()
    if args.provider == "yfinance" and not args.no_cache:
        provider = CachedProvider(base, QuoteCache(args.cache_db), run_date=now.date().isoformat())
    else:
        provider = base
    analysis = ClaudeCliAnalysis() if args.use_llm else FakeAnalysis()

    run = run_pipeline(
        universe, provider, analysis=analysis, top_n=args.top_n,
        created_at=now.isoformat(timespec="seconds"), max_workers=args.max_workers,
    )
    init_db(args.db)
    save_run(args.db, run)

    print(f"\nRun {run.created_at} — universe {run.universe_size}, gated out {len(run.gated_out)}")
    for bucket, picks in run.buckets.items():
        print(f"\n[{bucket}]")
        for p in picks:
            print(f"  {p.rank:>2}. {p.instrument.ticker:<12} score={p.composite:.3f}")
    print(f"\n{DISCLAIMER}\n")


if __name__ == "__main__":
    main()
