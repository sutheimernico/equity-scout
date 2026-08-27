"""Der Verlauf gemeldeter Chancen — Cooldown-Quelle und Material für die spätere Rückschau."""
from __future__ import annotations

from equity_scout.opportunity_storage import (
    last_notified_at,
    recent_opportunities,
    record_opportunity,
)

OPPORTUNITY = {
    "ticker": "MSFT",
    "name": "Microsoft",
    "headline": "Microsoft steht in seiner Kaufzone",
    "one_liner": "Kurs 100 $ · Limit 98 $",
    "verdict": "Starke Kennzahlen.",
    "why_now": ["Grund eins.", "Grund zwei."],
    "risk": "Unter 92 $ ist die Idee widerlegt.",
    "plan_line": "Kauflimit 98 $.",
    "score": 72,
    "stance": "kaufbereit",
    "price": 100.0,
    "currency": "USD",
    "limit": 98.0,
    "horizon": "lang",
    "explained_by": "llm",
    "track_record": "15 Vorschläge, p=0.94.",
}


def test_a_recorded_opportunity_comes_back_whole(tmp_path) -> None:
    db = str(tmp_path / "main.db")
    record_opportunity(db, OPPORTUNITY, notified_at="2026-08-27T06:00:00+00:00",
                       channels={"webpush": {"sent": 1}})
    rows = recent_opportunities(db)
    assert len(rows) == 1
    row = rows[0]
    # Die Listenfelder müssen als Listen zurückkommen, nicht als JSON-Text — sonst rendert
    # die App den String "[\"Grund eins.\"]".
    assert row["why_now"] == ["Grund eins.", "Grund zwei."]
    assert row["channels"]["webpush"]["sent"] == 1
    assert row["score"] == 72 and row["explained_by"] == "llm"


def test_last_notified_at_is_the_cooldown_source(tmp_path) -> None:
    db = str(tmp_path / "main.db")
    assert last_notified_at(db, "MSFT") is None
    record_opportunity(db, OPPORTUNITY, notified_at="2026-08-20T06:00:00+00:00")
    record_opportunity(db, OPPORTUNITY, notified_at="2026-08-27T06:00:00+00:00")
    assert last_notified_at(db, "MSFT") == "2026-08-27T06:00:00+00:00"
    assert last_notified_at(db, "AAPL") is None


def test_newest_first(tmp_path) -> None:
    db = str(tmp_path / "main.db")
    record_opportunity(db, {**OPPORTUNITY, "ticker": "OLD"}, notified_at="2026-08-01T06:00:00+00:00")
    record_opportunity(db, {**OPPORTUNITY, "ticker": "NEW"}, notified_at="2026-08-27T06:00:00+00:00")
    assert [r["ticker"] for r in recent_opportunities(db)] == ["NEW", "OLD"]
