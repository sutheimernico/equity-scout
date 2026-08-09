"""Insider-cluster SHADOW lane (v15 P2): register pre-registered predictions, trade nothing.

Reads the Form-4 events the LIVE collector already stored (`evidence_events`, filled by
scripts/run_evidence.py), detects >= 3-distinct-insider clusters inside the trailing
window and registers ONE prediction per fresh cluster in the evidence ledger under its
own source `insider_shadow`, horizon 63 TRADING days (pre-registered from the P2a study,
see evidence/insider_shadow.py). Resolution is not this script's job: the daily chain's
`run_resolve_evidence.py` step fills the outcomes against real forward returns vs SPY.

NO capital, NO broker order, NO position, NO promotion — this lane produces a track
record and nothing else. Whether it ever earns capital is Nico's decision on those
numbers, and there is deliberately no code path here that could make it.

Idempotent by construction: the ledger's UNIQUE(source, ticker, event_key) plus the
one-open-prediction-per-ticker skip mean a second run on the same day registers nothing.

Usage:
    uv run python scripts/run_insider_shadow.py [--db equity_scout.db]
        [--window-days 30] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

from equity_scout.constants import DEFAULT_DB_PATH, DISCLAIMER
from equity_scout.evidence.base import SOURCE_INSIDER, SOURCE_INSIDER_SHADOW
from equity_scout.evidence.edgar import resolve_user_agent
from equity_scout.evidence.insider_shadow import (
    DEFAULT_WINDOW_DAYS,
    SHADOW_HORIZON_TRADING_DAYS,
    STUDY_PRIOR,
    detect_clusters,
    shadow_events,
)
from equity_scout.evidence.ledger import (
    HORIZON_UNIT_TRADING,
    log_evidence,
    open_tickers,
    resolved_returns,
    stats_by_source,
)
from equity_scout.evidence.storage import events_in_window


def run_insider_shadow(
    db_path: str,
    *,
    now: str,
    env: dict,
    window_days: int = DEFAULT_WINDOW_DAYS,
    apply: bool = True,
) -> dict:
    """Detect clusters in the collected Form-4 events and register the fresh ones.

    Returns {status, detail, insider_events, clusters, skipped_open, registered,
    registered_tickers}. `status` is "unconfigured" when there is nothing to look at AND
    no EDGAR user agent is configured — without that distinction an unconfigured
    collector would read as "no insiders bought anything", which is a different claim.
    """
    grouped = events_in_window(db_path, window_days=window_days, now=now)
    insider_events = sum(
        1 for events in grouped.values() for e in events if e["source"] == SOURCE_INSIDER
    )
    if insider_events == 0 and resolve_user_agent(env) is None:
        return {
            "status": "unconfigured",
            "detail": (
                "EDGAR_USER_AGENT fehlt — der Form-4-Kollektor sammelt nichts, die Lane "
                "hat also nichts zu messen (keine Aussage über Insider-Käufe)"
            ),
            "insider_events": 0,
            "clusters": 0,
            "skipped_open": 0,
            "registered": 0,
            "registered_tickers": [],
        }

    clusters = detect_clusters(grouped)
    already_open = frozenset(open_tickers(db_path, source=SOURCE_INSIDER_SHADOW))
    events = shadow_events(clusters, skip_tickers=already_open)
    registered = (
        log_evidence(
            db_path,
            events,
            now=now,
            horizon_days=SHADOW_HORIZON_TRADING_DAYS,
            horizon_unit=HORIZON_UNIT_TRADING,
        )
        if apply and events
        else 0
    )
    return {
        "status": "ok",
        "detail": (
            f"{insider_events} Insider-Ereignis(se) im {window_days}-Tage-Fenster"
            f" -> {len(clusters)} Cluster"
        ),
        "insider_events": insider_events,
        "clusters": len(clusters),
        "skipped_open": len(clusters) - len(events),
        "registered": registered,
        "registered_tickers": [e.ticker for e in events],
    }


# Runtime state, not a report: .state/ is gitignored, so a daily rewrite creates no repo
# churn and no dashboard depends on it (the frontend belongs to another strand).
DEFAULT_STATUS_OUT = ".state/insider_shadow_status.json"

# Review PRECONDITIONS, not a promotion rule: they say when it is worth LOOKING at the
# track, never what to conclude. The arena gate's trade/PF criteria do not apply — this
# lane has no trades and no P&L, only resolved predictions.
MIN_RESOLVED_FOR_REVIEW = 30
MIN_DAYS_FOR_REVIEW = 60


def build_status(result: dict, *, now: str, db_path: str) -> dict:
    """The lane's whole public surface: what it is, what it registered, what it measured.

    The track block reports mean AND stderr AND hit rate together on purpose — the prior
    is "positive mean at a sub-50% hit rate", so any one of the three alone would mislead.
    """
    returns = resolved_returns(db_path, source=SOURCE_INSIDER_SHADOW)
    stats = stats_by_source(db_path).get(SOURCE_INSIDER_SHADOW, {})
    stderr = (
        round(statistics.stdev(returns) / len(returns) ** 0.5, 4) if len(returns) >= 2 else None
    )
    return {
        "lane": SOURCE_INSIDER_SHADOW,
        "generated_at": now,
        "shadow_only": True,
        "capital": 0,
        "broker_orders": 0,
        "what_this_is": (
            "Papier-Schattenlane: registriert vorab festgelegte Vorhersagen zu Insider-"
            "Clustern (>= 3 unabhängige Käufer) und misst sie gegen SPY. Kein Kapital, "
            "keine Orders, keine automatische Beförderung."
        ),
        "universe": (
            "die Ticker, die der Live-Form-4-Kollektor abdeckt (aktuelle Watchlist, "
            "evidence/form4.py) — keine Vollabdeckung des Universums"
        ),
        "pre_registration": {
            "horizon_trading_days": SHADOW_HORIZON_TRADING_DAYS,
            "n_hypotheses": 1,
            "why_one": (
                "Nur die r_3m-Zelle ist registriert. r_1w (+2,08 % ± 0,97pp) bleibt "
                "bewusst ungetestet: zwei Horizonte pro Ereignis verdoppeln die Tests "
                "für ein Signal und halbieren die Aussage eines Treffers."
            ),
            "prior": STUDY_PRIOR,
        },
        "last_run": {
            "status": result["status"],
            "detail": result["detail"],
            "insider_events": result["insider_events"],
            "clusters": result["clusters"],
            "skipped_open": result["skipped_open"],
            "registered": result["registered"],
            "registered_tickers": result["registered_tickers"],
        },
        "track": {
            "n_resolved": stats.get("n_resolved", 0),
            "n_open": stats.get("n_open", 0),
            "hit_rate": stats.get("hit_rate"),
            "mean_relative_return": stats.get("mean_relative_return"),
            "stderr": stderr,
            "reading_note": (
                "Mittelwert, Stderr und Trefferquote gehören zusammen gelesen: ein "
                "positiver Mittelwert bei einer Trefferquote unter 50 % heißt "
                "Ausreißer-getragen, nicht breit verdient."
            ),
        },
        "promotion": {
            "implemented": False,
            "decision_owner": "Nico",
            "min_resolved_for_review": MIN_RESOLVED_FOR_REVIEW,
            "min_days_for_review": MIN_DAYS_FOR_REVIEW,
            "note": (
                "Diese Lane kann sich nicht selbst befördern — es gibt keinen Codepfad "
                "dafür. Die Schwellen sagen, ab wann ein Blick lohnt, nicht was folgt. "
                "Erste Auflösungen frühestens ~93 Kalendertage nach der ersten "
                "Registrierung (63 Handelstage Horizont)."
            ),
        },
        "disclaimer": DISCLAIMER,
    }


def write_status(path: str, status: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--status-out", default=DEFAULT_STATUS_OUT)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument(
        "--dry-run", action="store_true", help="detect and report, register nothing"
    )
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_insider_shadow(
        args.db, now=now, env=dict(os.environ), window_days=args.window_days,
        apply=not args.dry_run,
    )
    mode = " [dry-run]" if args.dry_run else ""
    print(
        f"Insider-Schatten-Lane{mode} [{result['status']}]: {result['detail']};"
        f" neu registriert: {result['registered']}"
        f" ({result['skipped_open']} mit offener Vorhersage übersprungen)."
    )
    if result["registered_tickers"]:
        print("Registriert (Papier, ohne Kapital): " + ", ".join(result["registered_tickers"]))
    write_status(args.status_out, build_status(result, now=now, db_path=args.db))
    print(f"Status: {args.status_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
