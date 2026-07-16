"""v8 at-a-glance verdict: band logic, damping, and the surfaces that carry it."""
from __future__ import annotations

import sqlite3

from equity_scout.inbox_storage import create_pitch, init_inbox_db, load_pitches
from equity_scout.notify import notify_watchlist
from equity_scout.pitch import build_pitch, build_pitch_caption, compute_verdict

NOW = "2026-07-16T12:00:00+00:00"


def _entry(composite: float = 0.81, weakest: float = 0.5) -> dict:
    return {
        "ticker": "NVDA", "name": "NVIDIA Corp.", "composite": composite,
        "breakdown": {"value": 0.30, "quality": 0.65, "momentum": 0.92, "growth": 0.88,
                      "low_vol": 0.20},
        "price": 172.40, "entry_zone_low": 165.0, "entry_zone_high": 170.0,
        "bucket": "aggressive", "zone_note": "Kurs über Zone",
        "readings": [{"name": "dip", "score": weakest, "reason": "Momentum unter 20-Tage-Schnitt"}],
        "in_zone": True,
    }


def test_verdict_bands_follow_score():
    assert compute_verdict(_entry(composite=0.81))["level"] == "green"
    assert compute_verdict(_entry(composite=0.55))["level"] == "yellow"
    assert compute_verdict(_entry(composite=0.20))["level"] == "red"


def test_verdict_weak_signal_downgrades_one_level():
    dampened = compute_verdict(_entry(composite=0.81, weakest=0.1))
    assert dampened["level"] == "yellow"
    assert "gebremst" in dampened["why"]
    assert "Momentum unter 20-Tage-Schnitt" in dampened["why"]
    assert compute_verdict(_entry(composite=0.55, weakest=0.1))["level"] == "red"
    # red stays red — there is nothing below to downgrade to.
    assert compute_verdict(_entry(composite=0.20, weakest=0.1))["level"] == "red"


def test_verdict_handles_missing_readings():
    entry = _entry(composite=0.81)
    entry["readings"] = []
    verdict = compute_verdict(entry)
    assert verdict["level"] == "green"
    assert "laut Modell" in verdict["why"]


def test_caption_leads_with_verdict():
    caption = build_pitch_caption(_entry())
    assert caption.splitlines()[1].startswith("🟢 <b>Einstieg attraktiv</b>")


def test_long_pitch_carries_verdict_block():
    def fake_ask(question: str, context: str) -> str:
        return "Zwei Sätze Einordnung."

    pitch = build_pitch(_entry(composite=0.55), ask=fake_ask)
    assert "🟡 Einstieg neutral — " in pitch
    # The existing score-line contract stays untouched.
    assert "Einstiegs-Score: 55/100 (mittel)" in pitch


def test_inbox_persists_verdict_roundtrip(tmp_path):
    db = str(tmp_path / "inbox.db")
    create_pitch(
        db, ticker="NVDA", watchlist_id=None, price=172.4, composite=0.81,
        zone_low=165.0, zone_high=170.0, pitch="text", created_at=NOW,
        verdict="green", verdict_why="Starke Signale laut Modell: Momentum 92",
    )
    row = load_pitches(db)[0]
    assert row["verdict"] == "green"
    assert row["verdict_why"].startswith("Starke Signale")


def test_inbox_migration_adds_verdict_columns_to_old_db(tmp_path):
    """A pre-v8 inbox (no verdict columns) must open cleanly; old rows read as NULL."""
    db = str(tmp_path / "old.db")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE pitches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, ticker TEXT NOT NULL, watchlist_id INTEGER,
                price REAL NOT NULL, composite REAL NOT NULL,
                zone_low REAL NOT NULL, zone_high REAL NOT NULL,
                pitch TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                decided_at TEXT, telegram_message_id INTEGER
            )"""
        )
        conn.execute(
            "INSERT INTO pitches (created_at, ticker, price, composite, zone_low,"
            " zone_high, pitch) VALUES (?, 'OLD', 1, 0.5, 1, 2, 'p')",
            (NOW,),
        )
    init_inbox_db(db)
    row = load_pitches(db)[0]
    assert row["ticker"] == "OLD"
    assert row["verdict"] is None
    assert row["verdict_why"] is None


def test_notify_persists_computed_verdict(tmp_path):
    db = str(tmp_path / "inbox.db")
    watchlist = {"created_at": NOW, "entries": [_entry()]}
    created = notify_watchlist(
        db, watchlist,
        build=lambda entry, fund: "PITCH",
        send=None, enrich=None, now=NOW,
    )
    assert created == 1
    row = load_pitches(db)[0]
    assert row["verdict"] == "green"
    assert "laut Modell" in row["verdict_why"]
    assert row["pitch_html"] is None  # no build_html seam given -> honest absence


def test_notify_persists_html_variant_when_built(tmp_path):
    db = str(tmp_path / "inbox.db")
    watchlist = {"created_at": NOW, "entries": [_entry()]}
    notify_watchlist(
        db, watchlist,
        build=lambda entry, fund: "PITCH",
        build_html=lambda entry, fund: "<b>PITCH</b>",
        send=None, enrich=None, now=NOW,
    )
    assert load_pitches(db)[0]["pitch_html"] == "<b>PITCH</b>"
