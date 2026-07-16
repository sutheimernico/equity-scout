"""Read-through SQLite cache for quotes. Avoids re-fetching fresh data on every run.

Freshness is decided against an injected run-date (not wall-clock) so the cache is deterministic
and testable. A quote is fresh if it was fetched within `max_age_days` of the run-date.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from equity_scout.models import Instrument, Quote

_METRIC_FIELDS = (
    "trailing_pe", "price_to_book", "return_on_equity", "profit_margins",
    "revenue_growth", "earnings_growth", "momentum_6m", "volatility_6m", "price",
    # v8 D1: absent from pre-v8 cache rows -> Quote's dataclass default (None) applies,
    # an honest gap until the row refreshes.
    "high_52w_proximity",
)


def metrics_of(q: Quote) -> dict:
    """Quote -> plain metrics dict (drops the instrument, which the caller supplies)."""
    return {f: getattr(q, f) for f in _METRIC_FIELDS}


class QuoteCache:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = db_path
        with sqlite3.connect(db_path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS quote_cache ("
                "ticker TEXT PRIMARY KEY, fetched_on TEXT NOT NULL, metrics TEXT NOT NULL)"
            )

    def get(self, ticker: str) -> tuple[str, dict] | None:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                "SELECT fetched_on, metrics FROM quote_cache WHERE ticker = ?", (ticker,)
            ).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def put(self, ticker: str, metrics: dict, fetched_on: str) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT INTO quote_cache (ticker, fetched_on, metrics) VALUES (?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET "
                "fetched_on=excluded.fetched_on, metrics=excluded.metrics",
                (ticker, fetched_on, json.dumps(metrics)),
            )


def is_fresh(fetched_on: str, run_date: str, max_age_days: int) -> bool:
    delta = (date.fromisoformat(run_date) - date.fromisoformat(fetched_on)).days
    return 0 <= delta <= max_age_days


def is_empty_metrics(metrics: dict) -> bool:
    """All-None metrics are a failed fetch's fallback quote, not data (2026-07-14 world-scan
    lesson: caching those as fresh poisoned a whole week of runs)."""
    return all(metrics.get(f) is None for f in _METRIC_FIELDS)


class CachedProvider:
    """Decorator provider: serve from cache when fresh, else delegate to inner and cache it.

    Empty (all-None) rows are treated as cache MISSES on read and never stored on write:
    a rate-limited fetch must be retried on the next run, not replayed for max_age_days.
    """

    def __init__(self, inner, cache: QuoteCache, run_date: str, max_age_days: int = 1) -> None:
        self._inner = inner
        self._cache = cache
        self._run_date = run_date
        self._max_age_days = max_age_days

    def fetch_quote(self, instrument: Instrument) -> Quote:
        cached = self._cache.get(instrument.ticker)
        if (
            cached is not None
            and is_fresh(cached[0], self._run_date, self._max_age_days)
            and not is_empty_metrics(cached[1])
        ):
            return Quote(instrument=instrument, **cached[1])
        quote = self._inner.fetch_quote(instrument)
        metrics = metrics_of(quote)
        if not is_empty_metrics(metrics):
            self._cache.put(instrument.ticker, metrics, self._run_date)
        return quote
