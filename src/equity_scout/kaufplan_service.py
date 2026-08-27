"""Kaufpläne bauen — eine Quelle für den Endpunkt UND den Melde-Job (2026-08-27).

Die Logik lag bis heute inline in `api.py::kaufplan`. Der neue Chancen-Job braucht exakt
dieselben Pläne; sie ein zweites Mal zu tippen hieße, dass die Meldung und die Ansicht
irgendwann auseinanderlaufen — und zwar unbemerkt, weil beide für sich plausibel aussehen.
Deshalb Extraktion statt Kopie: `api.py` ruft dieselbe Funktion auf.

Reine Bewegung von Code; das Verhalten des Endpunkts ändert sich nicht.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from equity_scout.briefs import build_brief, rank_entries
from equity_scout.buy_plan import (
    BuyPlan,
    build_plan,
    buy_limit_for,
    buyers_from_events,
    relabel_tranches,
    sort_plans,
    stance_for,
    tranche_basis,
)
from equity_scout.evidence.storage import events_in_window
from equity_scout.fundamentals import fetch_fundamentals_cached
from equity_scout.insights_storage import load_insights, load_price_series
from equity_scout.ml.model_registry import entry_champion
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.suggestion_storage import load_latest_review

# Der Rückschau-Horizont, der an jedem Plan hängt. Bewusst 20 Tage: das passt zu der
# Haltedauer, über die jemand nach einem Screen-Vorschlag entscheidet. Die 5-Tage-Zahl
# sähe besser aus und beantwortet eine andere Frage.
REVIEW_HORIZON_DAYS = 20


def review_for(db_path: str, source: str) -> dict | None:
    """Die gemessene Bilanz EINER Vorschlagsquelle — oder None, solange nie gemessen wurde."""
    review = load_latest_review(db_path)
    if review is None:
        return None
    for summary in review.get("summaries", []):
        if (
            summary.get("source") == source
            and summary.get("horizon_days") == REVIEW_HORIZON_DAYS
        ):
            return {
                "computed_at": review.get("computed_at"),
                "n_independent": summary.get("n_independent"),
                "hit_rate": summary.get("hit_rate"),
                "mean_excess_pct": summary.get("mean_excess_pct"),
                "line": summary.get("line"),
            }
    return None


def build_buy_plans(db_path: str, *, limit: int = 12) -> dict:
    """{generated_at, plans (BuyPlan-Objekte), ready_count, note} für die aktuelle Watchlist."""
    limit = max(1, min(limit, 20))
    watchlist = load_latest_watchlist(db_path)
    entries = rank_entries((watchlist or {}).get("entries", []))[:limit]
    if not entries:
        return {
            "generated_at": None,
            "plans": [],
            "ready_count": 0,
            "note": "Noch keine Watchlist berechnet.",
        }

    def _fetch(ticker: str):  # noqa: ANN202
        try:
            return fetch_fundamentals_cached(ticker)
        except Exception:  # noqa: BLE001 - ein Titel darf die Liste nie kippen
            return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        fetched = list(pool.map(_fetch, [e["ticker"] for e in entries]))

    insights = load_insights(db_path)
    series = load_price_series(db_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    events = events_in_window(
        db_path, window_days=90, now=now, tickers=[e["ticker"] for e in entries]
    )
    review = review_for(db_path, "rank")

    import equity_scout.entry as entry_mod

    champ = entry_champion(db_path, family="entry_tb")
    barrier_config = champ[2].get("barrier_config") if champ is not None else None

    plans: list[BuyPlan] = []
    for entry, fundamentals in zip(entries, fetched, strict=True):
        ticker = entry["ticker"]
        cached = series.get(ticker)
        target_stop = (
            entry_mod.resolve_target_stop(cached["closes"], barrier_config) if cached else None
        )
        brief = build_brief(
            entry, fundamentals, insight=insights.get(ticker), chart=None,
            target_stop=target_stop,
        )
        # Die Leiter hängt an der Zahl, die auch in die Order geht — nie am aktuellen Kurs,
        # wenn das Limit woanders liegt.
        stance = stance_for(
            in_zone=brief["in_zone"], price=brief["price"],
            zone_low=brief["zone_low"], zone_high=brief["zone_high"],
        )
        basis = tranche_basis(
            stance, price=brief["price"],
            limit=buy_limit_for(stance, price=brief["price"], zone_high=brief["zone_high"]),
        )
        plans.append(build_plan(
            brief,
            horizon="lang",
            evidence_state=(
                review["line"] if review
                else "Noch nie gemessen — die Bilanz dieser Quelle ist unbekannt."
            ),
            breakdown=entry.get("breakdown"),
            tranches=relabel_tranches(
                [
                    {"label": t.label, "share": t.fraction, "trigger_price": t.trigger_price}
                    for t in entry_mod.dip_tranche_plan(basis)
                ],
                at_limit=basis != brief["price"],
            ) if basis is not None else [],
            buyers=buyers_from_events(events.get(ticker, [])),
            track_record=review,
        ))

    ordered = sort_plans(plans)
    return {
        "generated_at": (watchlist or {}).get("created_at"),
        "plans": ordered,
        "ready_count": sum(1 for p in plans if p.entry.stance == "kaufbereit"),
        "note": None,
    }
