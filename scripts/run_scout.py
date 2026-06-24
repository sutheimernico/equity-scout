"""CLI: run the funnel, persist a snapshot, print a summary.

Default provider is 'fake' for a deterministic offline run; pass --provider yfinance for live.
LLM theses off by default (--use-llm to enable).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from equity_scout.analysis import ClaudeCliAnalysis, FakeAnalysis
from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_UNIVERSE_PATH, DISCLAIMER
from equity_scout.data.fake_provider import FakeProvider
from equity_scout.data.yf_provider import YFinanceProvider
from equity_scout.pipeline import run_pipeline
from equity_scout.storage import init_db, save_run
from equity_scout.universe import load_universe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=DEFAULT_UNIVERSE_PATH)
    ap.add_argument("--db", default=DEFAULT_DB_PATH)
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--provider", choices=["fake", "yfinance"], default="fake")
    ap.add_argument("--use-llm", action="store_true")
    args = ap.parse_args()

    universe = load_universe(args.universe)
    provider = YFinanceProvider() if args.provider == "yfinance" else FakeProvider()
    analysis = ClaudeCliAnalysis() if args.use_llm else FakeAnalysis()

    run = run_pipeline(
        universe, provider, analysis=analysis, top_n=args.top_n,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
