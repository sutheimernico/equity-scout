"""Watchlist builder: funnel finalists -> entry zones + sub-signal readings.

Pure: histories are passed in (fetched by the CLI), finalists are plain dicts
(shape of a JSON-round-tripped Pick: ticker/name/bucket/breakdown) so both live
runs and stored runs feed the same code path.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from equity_scout.entry import EntryPlan, compute_entry_plan
from equity_scout.signals import (
    SignalReading,
    composite_score,
    dip_quality,
    momentum,
    value_gap,
)

History = tuple[list[float], list[float], list[float]]  # closes, highs, lows


@dataclass(frozen=True)
class WatchlistEntry:
    ticker: str
    name: str
    bucket: str
    price: float
    entry_zone_low: float
    entry_zone_high: float
    # price / zone_high - 1.0; <= 0 means at or below the zone's upper edge
    # (in_zone is the containment check)
    proximity: float
    in_zone: bool
    composite: float
    readings: list[SignalReading]
    reference_note: str  # EntryPlan.reference_note, carried through for the UI/pitch


@dataclass(frozen=True)
class Watchlist:
    created_at: str
    entries: list[WatchlistEntry]  # sorted by composite, best first
    skipped: dict[str, str] = field(default_factory=dict)  # ticker -> reason


def entry_zone(plan: EntryPlan) -> tuple[float, float] | None:
    """Derive [low, high] from the plan's support levels, capped at the 200-day SMA.

    high = best (highest) support, but never above the long-term anchor
    low  = worst (lowest) support minus one ATR of buffer (if ATR is known),
           capped at 20% below the lowest support so an oversized ATR (deep-drawdown,
           high-vol names) can never push the zone negative
    None when the plan has no support levels at all (degenerate history).
    """
    supports = [lvl.price for lvl in plan.levels if lvl.kind == "support"]
    if not supports:
        return None
    high = max(supports)
    if plan.sma200 is not None:
        high = min(high, plan.sma200)
    low = max(min(supports) - (plan.atr or 0.0), min(supports) * 0.8)
    # Round before the degenerate check so a sub-cent band cannot collapse to low == high.
    low, high = round(low, 2), round(high, 2)
    if low >= high:  # single tight support cluster: pad a 2% band below
        low = round(high * 0.98, 2)
    return low, high


def build_watchlist(
    finalists: list[dict], histories: dict[str, History], created_at: str
) -> Watchlist:
    """Score every finalist with usable history; report the rest under `skipped`."""
    entries: list[WatchlistEntry] = []
    skipped: dict[str, str] = {}
    for pick in finalists:
        ticker = pick["ticker"]
        closes, highs, lows = histories.get(ticker, ([], [], []))
        # Mirror entry.py's cleaning: non-finite values (inf/nan from a bad feed) must not
        # pass the guard, or compute_entry_plan raises and one bad ticker kills the run.
        usable = [c for c in closes if isinstance(c, (int, float)) and math.isfinite(c) and c > 0]
        if len(usable) < 2:
            skipped[ticker] = "keine verwertbare Kurshistorie"
            continue
        plan = compute_entry_plan(ticker, closes, highs, lows)
        zone = entry_zone(plan)
        if zone is None:
            skipped[ticker] = "keine Support-Levels ableitbar"
            continue
        low, high = zone
        breakdown = pick.get("breakdown", {})
        readings = [
            dip_quality(breakdown, plan),
            value_gap(breakdown, plan),
            momentum(breakdown, plan, closes),
        ]
        entries.append(
            WatchlistEntry(
                ticker=ticker,
                name=pick.get("name", ticker),
                bucket=pick.get("bucket", ""),
                price=plan.price,
                entry_zone_low=low,
                entry_zone_high=high,
                proximity=plan.price / high - 1.0,
                in_zone=low <= plan.price <= high,
                composite=composite_score(readings),
                readings=readings,
                reference_note=plan.reference_note,
            )
        )
    entries.sort(key=lambda e: e.composite, reverse=True)
    return Watchlist(created_at=created_at, entries=entries, skipped=skipped)
