"""Nightly cache warm-up: fetch one universe segment through the read-through cache.

Purpose: the weekly full screen died on yfinance rate limits (2026-07-14: 5,275 gated, most
"missing price history"). Instead of one marathon run, a gentle nightly rotation keeps the
cache warm; the Monday screen then ranks from cache (--cache-max-age 7) and only live-fetches
misses. Sectors discovered on the way are persisted to instrument_meta.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_UNIVERSE_PATH
from equity_scout.data.cache import CachedProvider, QuoteCache
from equity_scout.data.fetch import fetch_all, rotation_segment
from equity_scout.data.universe_storage import load_instrument_meta, upsert_instrument_meta
from equity_scout.data.yf_provider import FetchStats, YFinanceProvider
from equity_scout.pipeline import harvest_sectors
from equity_scout.universe import apply_meta_overlay, load_universe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=DEFAULT_UNIVERSE_PATH)
    ap.add_argument("--db", default=DEFAULT_DB_PATH)
    ap.add_argument("--cache-db", default="equity_scout_cache.db")
    ap.add_argument("--segments", type=int, default=6)
    ap.add_argument("--max-workers", type=int, default=2,
                    help="Deliberately low — this is a background crawl under the rate limit.")
    ap.add_argument("--cache-max-age", type=int, default=6,
                    help="Skip names fetched within N days (already warm).")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    universe = apply_meta_overlay(load_universe(args.universe), load_instrument_meta(args.db))
    by_ticker = {i.ticker: i for i in universe}
    segment_tickers = rotation_segment(list(by_ticker), segments=args.segments, on=now.date())
    segment = [by_ticker[t] for t in segment_tickers]

    stats = FetchStats()
    provider = CachedProvider(
        YFinanceProvider(stats=stats), QuoteCache(args.cache_db),
        run_date=now.date().isoformat(), max_age_days=args.cache_max_age,
    )
    quotes = fetch_all(provider, segment, max_workers=args.max_workers)
    sectors = harvest_sectors(segment, quotes)
    upsert_instrument_meta(args.db, sectors, source="yfinance.info",
                           updated_at=now.date().isoformat())

    # stats.attempted counts only live fetches (cache hits never reach the provider), so this
    # line directly shows how warm the segment already was.
    s = stats.summary()
    print(
        f"prefetch {now.date().isoformat()}: segment {len(segment)}/{len(universe)} tickers, "
        f"{s['attempted']} live fetches, {s['info_failed']} info-failures, "
        f"{s['closes_failed']} price-failures, {len(sectors)} sectors persisted"
    )


if __name__ == "__main__":
    main()
