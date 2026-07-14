"""Fetch helpers: retry with exponential backoff + bounded-parallel fetch.

Network politeness for large universes. Backoff is pure and unit-tested; sleeping is injected so
tests stay instant and deterministic.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from equity_scout.data.provider import MarketDataProvider
from equity_scout.models import Instrument, Quote

logger = logging.getLogger(__name__)


def retry_delays(attempts: int, base: float = 0.5, cap: float = 8.0) -> list[float]:
    """Backoff delays for the gaps BETWEEN attempts (length == attempts - 1)."""
    return [min(cap, base * (2 ** i)) for i in range(max(0, attempts - 1))]


def is_rate_limit_error(exc: Exception) -> bool:
    """Duck-typed: yfinance raises YFRateLimitError, but this module stays yfinance-free."""
    return "ratelimit" in type(exc).__name__.lower()


def with_retry(
    fn: Callable[[], object],
    attempts: int = 3,
    base: float = 0.5,
    cap: float = 8.0,
    rate_limit_base: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
):
    """Call fn(); on exception retry up to `attempts` total with backoff. Re-raise the last error.

    Rate-limit errors get a MUCH longer backoff (30s/60s/... instead of sub-second): Yahoo
    throttles per IP, and hammering through the block just extends it — the 6.6k-universe run
    died on exactly this (2026-07-14). The long waits make a big first crawl slow but finish."""
    delays = retry_delays(attempts, base, cap)
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - provider errors are opaque; retry then surface
            last_exc = exc
            logger.warning("with_retry: attempt %d/%d failed: %r", i + 1, attempts, exc)
            if i < len(delays):
                if is_rate_limit_error(exc):
                    sleep(rate_limit_base * (2**i))
                else:
                    sleep(delays[i])
    assert last_exc is not None
    raise last_exc


def fetch_all(
    provider: MarketDataProvider, instruments: list[Instrument], max_workers: int = 8
) -> list[Quote]:
    """Fetch quotes for all instruments, bounded-parallel, preserving input order."""
    if max_workers <= 1:
        return [provider.fetch_quote(i) for i in instruments]
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(provider.fetch_quote, instruments))
