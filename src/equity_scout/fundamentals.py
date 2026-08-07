"""Per-ticker fundamentals + third-party analyst consensus for the pitch.

Lazy yfinance `.info` read (US-heavy coverage; EU/JP often missing) behind a thin
function so the pitch path is testable and offline-safe. EVERYTHING is optional:
any missing field comes back None and the pitch renders an honest gap. The analyst
target is THIRD-PARTY consensus (sell-side analysts), never our own forecast — the
pitch labels it as such.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Fundamentals:
    trailing_pe: float | None       # KGV
    analyst_target: float | None    # mean sell-side target price
    analyst_count: int | None       # number of analyst opinions behind the target
    currency: str | None
    # sector/industry answer "what does this company do" at a glance (briefs.py's phone
    # card); same `.info` payload as the fields above, so this is not a second fetch.
    sector: str | None = None
    industry: str | None = None
    # 52-week high: the honest reference figure for names WITHOUT analyst coverage
    # (CEFs, small caps) — geometry, never a price target (Nico 2026-08-07: "irgendwelche
    # Kursziele muss es da geben"). Same `.info` payload, no extra fetch.
    year_high: float | None = None


def _finite(value: object) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def from_info(info: dict) -> Fundamentals:
    """Pure: map a yfinance `.info`-shaped dict to Fundamentals (all fields optional)."""
    count = info.get("numberOfAnalystOpinions")
    try:
        count = int(count) if count is not None else None
    except (TypeError, ValueError):
        count = None
    return Fundamentals(
        trailing_pe=_finite(info.get("trailingPE")),
        analyst_target=_finite(info.get("targetMeanPrice")),
        analyst_count=count if (count or 0) > 0 else None,
        currency=info.get("currency") or None,
        sector=info.get("sector") or None,
        industry=info.get("industry") or None,
        year_high=_finite(info.get("fiftyTwoWeekHigh")),
    )


def fetch_fundamentals(ticker: str) -> Fundamentals:
    """Live fetch via yfinance `.info` (lazy import, network). Returns an all-None
    Fundamentals on any failure — never raises into the pitch path."""
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info
        return from_info(info if isinstance(info, dict) else {})
    except Exception:
        return Fundamentals(None, None, None, None)


# Fundamentals move on quarterly reports, not on minutes, while /api/briefs is hit on
# every single app open on the phone. Without a cache that is five yfinance calls per
# visit against a free, aggressively rate-limited endpoint — this project has already lost
# 5,275 of 6,318 tickers to that limit once (2026-07-14). Deliberately in-process rather
# than in SQLite: the dashboard service is long-lived, so a restart costs one refetch, and
# a second persistence layer for data that is already cheap to re-derive is not worth it.
FUNDAMENTALS_TTL_SECONDS = 6 * 3600
_cache: dict[str, tuple[float, Fundamentals]] = {}


def _is_empty(value: Fundamentals) -> bool:
    return all(getattr(value, f.name) is None for f in fields(value))


def fetch_fundamentals_cached(
    ticker: str,
    *,
    fetch: Callable[[str], Fundamentals] = fetch_fundamentals,
    ttl_seconds: float = FUNDAMENTALS_TTL_SECONDS,
    now: float | None = None,
) -> Fundamentals:
    """TTL-cached `fetch_fundamentals` for the API path.

    An ALL-NONE result is never cached: that is what a rate-limited or failed fetch looks
    like, and replaying it for hours would turn one bad moment into a day of empty cards
    (same rule as data/cache.py's is_empty_metrics guard). `now`/`fetch` are injectable so
    the TTL is testable without sleeping or touching the network.
    """
    stamp = time.monotonic() if now is None else now
    hit = _cache.get(ticker)
    if hit is not None and stamp - hit[0] < ttl_seconds:
        return hit[1]
    value = fetch(ticker)
    if not _is_empty(value):
        _cache[ticker] = (stamp, value)
    return value
