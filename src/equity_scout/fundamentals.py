"""Per-ticker fundamentals + third-party analyst consensus for the pitch.

Lazy yfinance `.info` read (US-heavy coverage; EU/JP often missing) behind a thin
function so the pitch path is testable and offline-safe. EVERYTHING is optional:
any missing field comes back None and the pitch renders an honest gap. The analyst
target is THIRD-PARTY consensus (sell-side analysts), never our own forecast — the
pitch labels it as such.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


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
