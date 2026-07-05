"""Watchlist builder: funnel finalists -> entry zones + sub-signal readings.

Pure: histories are passed in (fetched by the CLI), finalists are plain dicts
(shape of a JSON-round-tripped Pick: ticker/name/bucket/breakdown) so both live
runs and stored runs feed the same code path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from equity_scout.entry import EntryPlan, clean_prices, compute_entry_plan
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
    zone_note: str  # German zone-status note, derived from the same values as in_zone below
    breakdown: dict[str, float]  # finalist's full funnel breakdown (incl. growth/low_vol) for ML context
    # Dip scale-in plan (now / −7 % / −15 %) from EntryPlan.dip_tranches, as plain dicts so it
    # JSON-round-trips through radar_storage's watchlists.data blob with no schema change.
    tranches: list[dict] = field(default_factory=list)


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


def zone_note(price: float, low: float, high: float, in_zone: bool, proximity: float) -> str:
    """German zone-status note, built from the exact values that produced `in_zone` — cannot
    contradict it (unlike entry.py's independent near_reference/reference_note, which compares
    against different levels and disagrees with in_zone ~15% of the time)."""
    if in_zone:
        return f"Kurs in der Entry-Zone ({low:.2f}–{high:.2f})."
    if price < low:
        return "Kurs unter der Entry-Zone — tiefer als die Support-Levels."
    return f"Kurs {proximity * 100:+.1f} % über der Entry-Zone."


def build_watchlist(
    finalists: list[dict], histories: dict[str, History], created_at: str
) -> Watchlist:
    """Score every finalist with usable history; report the rest under `skipped`."""
    entries: list[WatchlistEntry] = []
    skipped: dict[str, str] = {}
    for pick in finalists:
        ticker = pick["ticker"]
        closes, highs, lows = histories.get(ticker, ([], [], []))
        # Same predicate compute_entry_plan uses internally (imported, not duplicated): a
        # non-finite value (inf/nan from a bad feed) must not pass the guard, or
        # compute_entry_plan raises and one bad ticker kills the run.
        usable = clean_prices(closes)
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
        proximity = round(plan.price / high - 1.0, 4)
        in_zone = low <= plan.price <= high
        entries.append(
            WatchlistEntry(
                ticker=ticker,
                name=pick.get("name", ticker),
                bucket=pick.get("bucket", ""),
                price=plan.price,
                entry_zone_low=low,
                entry_zone_high=high,
                proximity=proximity,
                in_zone=in_zone,
                composite=composite_score(readings),
                readings=readings,
                zone_note=zone_note(plan.price, low, high, in_zone, proximity),
                breakdown=breakdown,
                tranches=[asdict(t) for t in plan.dip_tranches],
            )
        )
    entries.sort(key=lambda e: e.composite, reverse=True)
    return Watchlist(created_at=created_at, entries=entries, skipped=skipped)
