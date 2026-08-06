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

__all__ = [
    "score_band",
    "zone_gap",
    "entry_note",
    "rank_entries",
    "build_brief",
    "pitch_market_context",
]


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
        # NOT "zu teuer" (the wording this shipped with on 2026-08-04). The zone is a
        # SUPPORT band, so above it says the price has run far from its last floor — a
        # TIMING statement. "Teuer" is a VALUE statement, and on a card that also shows a
        # +69 % analyst upside the two read as a flat contradiction ("Warum sollte die
        # Aktie dann zu teuer sein, wenn noch so ein hohes Potenzial?", Nico 2026-08-06).
        # Same class of error as "noch günstiger" below, corrected the same way: state what
        # the geometry means and let `entry_note` relate it to the analyst view.
        return float(gap), f"{gap} % über der Einstiegszone"
    gap = round((1.0 - price / zone_low) * 100)
    # NOT "noch günstiger" (the wording this shipped with on 2026-08-04, which read as a buy
    # signal and was understood as one). The zone is a SUPPORT band — `radar.entry_zone` runs
    # from the lowest support minus one ATR up to the highest one — so below it means every
    # support level has broken, with nothing holding underneath. `in_zone` is a pitch gate
    # (notify.py, lanes.py), so this side is just as much a "not now" as being too expensive.
    # Kept in step with radar.zone_note's "tiefer als die Support-Levels".
    return float(gap), f"{gap} % unter der Zone — Support gebrochen"


def entry_note(*, in_zone: bool, gap_pct: float | None, upside_pct: float | None) -> str:
    """One sentence relating the two things the card shows, because they answer different
    questions and looked like a contradiction when shown side by side.

    - The analyst upside is a VALUE claim over ~12 months, made by other people.
    - The entry zone is a TIMING observation from our own support levels.

    A stock can be worth more (analysts) and still sit far above its last floor (us) — that
    is not a conflict, it is two axes. Naming both axes is what makes the card readable;
    saying which one should win would be advice, which this project does not give.
    """
    has_upside = upside_pct is not None
    if in_zone:
        if has_upside and upside_pct > 0:
            return (
                f"Kurs liegt im Support-Bereich (Zeitpunkt), Analysten sehen "
                f"{round(upside_pct)} % Luft (Wert)."
            )
        if has_upside:
            return (
                "Kurs liegt im Support-Bereich (Zeitpunkt), aber die Analysten sehen "
                "kein Aufwärtspotenzial (Wert)."
            )
        return "Kurs liegt im Support-Bereich (Zeitpunkt); keine Analystenschätzung zum Wert."
    if gap_pct is not None and gap_pct < 0:
        # Below the zone: every support has broken, and no price target changes that.
        base = f"Alle Support-Levels sind gefallen ({abs(round(gap_pct))} % darunter)"
        if has_upside and upside_pct > 0:
            return f"{base} — kein Halt mehr, unabhängig vom Kursziel der Analysten."
        return f"{base} — kein Halt mehr darunter."
    distance = f"{round(gap_pct)} % über dem letzten Support" if gap_pct is not None else "über der Zone"
    if has_upside and upside_pct > 0:
        return (
            f"Kein Widerspruch, zwei Fragen: Analysten sehen {round(upside_pct)} % Luft "
            f"(Wert), der Kurs steht aber {distance} (Zeitpunkt) — ein Rücksetzer hätte "
            "Fallhöhe."
        )
    if has_upside:
        return f"Kurs {distance} (Zeitpunkt), und die Analysten sehen keine Luft (Wert)."
    return f"Kurs {distance} (Zeitpunkt); keine Analystenschätzung zum Wert."


_EMPTY_PITCH_CONTEXT: dict = {
    "name": None,
    "current_price": None,
    "currency": None,
    "in_zone": None,
    "zone_gap_pct": None,
    "zone_verdict": None,
    "analyst_target": None,
    "analyst_count": None,
    "analyst_upside_pct": None,
    "entry_note": None,
}


def pitch_market_context(entry: dict | None, fundamentals: Fundamentals | None) -> dict:
    """Today's market context for one inbox pitch, from the CURRENT watchlist entry.

    The pitch row stores price and zone AT PITCH TIME; the decision Nico makes is about
    TODAY ("ist gerade ein guter Einstiegspreis?", 2026-08-06). entry=None — the ticker
    has dropped off the watchlist — degrades every field to None so the card shows an
    honest gap instead of presenting the stale pitch-time numbers as current.
    """
    if entry is None:
        return dict(_EMPTY_PITCH_CONTEXT)
    price = entry["price"]
    gap_pct, verdict = zone_gap(price, entry["entry_zone_low"], entry["entry_zone_high"])
    target = fundamentals.analyst_target if fundamentals else None
    upside = round((target / price - 1.0) * 100, 1) if target is not None and price > 0 else None
    return {
        "name": entry["name"],
        "current_price": price,
        "currency": fundamentals.currency if fundamentals else None,
        "in_zone": entry["in_zone"],
        "zone_gap_pct": gap_pct,
        "zone_verdict": verdict,
        "analyst_target": target,
        "analyst_count": fundamentals.analyst_count if fundamentals else None,
        "analyst_upside_pct": upside,
        "entry_note": entry_note(in_zone=entry["in_zone"], gap_pct=gap_pct, upside_pct=upside),
    }


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
        # Relates the timing observation above to the value claim below, so the card does
        # not read as self-contradicting. Built here, not in the frontend: the support-band
        # semantics live on this side (see zone_gap) and must not be encoded twice.
        "entry_note": entry_note(
            in_zone=entry["in_zone"], gap_pct=gap_pct, upside_pct=upside
        ),
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
