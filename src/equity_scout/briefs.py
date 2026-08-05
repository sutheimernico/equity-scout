"""Pure logic for the phone-card "brief" bundle (`GET /api/briefs`).

The cockpit's watchlist row used to show `48 · 1915.50 · IN ZONE` — a score, a price,
a boolean, nothing a lay reader can act on. This module answers the four questions the
card needs in plain German, from data the funnel and the fundamentals seam already
have: what the company does (sector/industry), whether the price is a good entry (the
zone verdict), what the upside would be (analyst consensus, never our own guess), and
leaves the news summary to the caller.

No network, no DB here — `api.py`'s endpoint does the I/O (watchlist load + fundamentals
fetch) and calls `rank_entries` + `build_brief` per row, so this stays unit-testable
offline.
"""
from __future__ import annotations

from equity_scout.fundamentals import Fundamentals
from equity_scout.pitch import score_band  # single source of the niedrig/mittel/hoch scale

__all__ = ["score_band", "zone_gap", "rank_entries", "build_brief"]


def zone_gap(price: float, zone_low: float, zone_high: float) -> tuple[float | None, str]:
    """(gap_pct, verdict) against the NEAREST zone edge: 0.0 / "im Einstiegsbereich" when
    the price is inside; otherwise the whole-number % above `zone_high` or below
    `zone_low`. A zero/negative price is an honest gap (None), never a division blow-up.
    """
    if price <= 0:
        return None, "kein gültiger Kurs verfügbar"
    if zone_low <= price <= zone_high:
        return 0.0, "im Einstiegsbereich"
    if price > zone_high:
        gap = round((price / zone_high - 1.0) * 100)
        return float(gap), f"{gap} % über der Zone — zu teuer"
    gap = round((1.0 - price / zone_low) * 100)
    # NOT "noch günstiger" (the wording this shipped with on 2026-08-04, which read as a buy
    # signal and was understood as one). The zone is a SUPPORT band — `radar.entry_zone` runs
    # from the lowest support minus one ATR up to the highest one — so below it means every
    # support level has broken, with nothing holding underneath. `in_zone` is a pitch gate
    # (notify.py, lanes.py), so this side is just as much a "not now" as being too expensive.
    # Kept in step with radar.zone_note's "tiefer als die Support-Levels".
    return float(gap), f"{gap} % unter der Zone — Support gebrochen"


def rank_entries(entries: list[dict]) -> list[dict]:
    """In-zone first, then composite descending — the exact ordering
    `frontend/src/components/StockList.tsx`'s `rank()` already uses, so `/api/briefs`
    never disagrees with what the cockpit shows elsewhere."""
    return sorted(entries, key=lambda e: (not e["in_zone"], -e["composite"]))


def build_brief(
    entry: dict,
    fundamentals: Fundamentals | None,
    *,
    insight: dict | None = None,
    chart: dict | None = None,
) -> dict:
    """Assemble one phone-card row from a watchlist entry plus optional fundamentals.
    A missing/failed fundamentals lookup degrades every fundamentals-derived field to
    null — never a placeholder number standing in for an unknown.

    `insight`/`chart` are the pre-generated caches from insights_storage (nightly
    `scripts/run_insights.py`). Both default to None: a fresh DB, or a stock outside the
    generator's top-N, renders an honest "noch nicht erzeugt" rather than blocking the
    card on a 5-second LLM call.

    `model_target`/`model_stop` are always null here: the entry_tb champion barrier
    computation (`entry.compute_target_stop`) needs its own price-history fetch per
    ticker (see `/api/entry/{ticker}`), which this endpoint deliberately does not add
    on top of the fundamentals fan-out — and no `entry_tb` champion is registered yet
    anyway, so today it would be an honest None regardless.
    """
    price = entry["price"]
    score = round(entry["composite"] * 100)
    gap_pct, verdict = zone_gap(price, entry["entry_zone_low"], entry["entry_zone_high"])

    target = fundamentals.analyst_target if fundamentals else None
    upside = round((target / price - 1.0) * 100, 1) if target is not None and price > 0 else None

    return {
        "ticker": entry["ticker"],
        "name": entry["name"],
        "sector": fundamentals.sector if fundamentals else None,
        "industry": fundamentals.industry if fundamentals else None,
        "currency": fundamentals.currency if fundamentals else None,
        "price": price,
        "score": score,
        "score_band": score_band(score),
        "zone_low": entry["entry_zone_low"],
        "zone_high": entry["entry_zone_high"],
        "in_zone": entry["in_zone"],
        "zone_gap_pct": gap_pct,
        "zone_verdict": verdict,
        "analyst_target": target,
        "analyst_count": fundamentals.analyst_count if fundamentals else None,
        "analyst_upside_pct": upside,
        "trailing_pe": fundamentals.trailing_pe if fundamentals else None,
        "model_target": None,
        "model_stop": None,
        # Pre-generated, never computed here: see the docstring.
        "insight": insight,
        "chart": chart,
    }
