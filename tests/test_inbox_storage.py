"""Inbox storage: pitch lifecycle + cooldown lookups (tmp_path SQLite)."""
from __future__ import annotations

from equity_scout.inbox_storage import (
    create_pitch,
    decide_pitch,
    init_inbox_db,
    last_pitch_at,
    load_pitches,
    set_message_id,
)

T0 = "2026-07-05T10:00:00+00:00"
T1 = "2026-07-05T11:00:00+00:00"


def _pitch_row(db, ticker="EXE", created_at=T0):
    return create_pitch(
        db,
        ticker=ticker,
        watchlist_id=1,
        price=90.72,
        composite=0.592,
        zone_low=84.77,
        zone_high=103.01,
        pitch="Pitch-Text",
        created_at=created_at,
    )


def test_create_and_load_open_pitch(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _pitch_row(db)
    pitches = load_pitches(db)
    assert len(pitches) == 1
    p = pitches[0]
    assert (p["id"], p["ticker"], p["status"], p["decided_at"]) == (pitch_id, "EXE", "open", None)
    # Pin the value columns field-by-field: swapped zone_low/zone_high (or
    # price/composite) in a caller's create_pitch call must not survive the suite.
    assert p["zone_low"] == 84.77
    assert p["zone_high"] == 103.01
    assert p["price"] == 90.72
    assert p["composite"] == 0.592


def test_decide_pitch_transitions_only_from_open(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _pitch_row(db)
    assert decide_pitch(db, pitch_id, "buy", decided_at=T1) is True
    assert decide_pitch(db, pitch_id, "pass", decided_at=T1) is False  # already decided
    assert decide_pitch(db, 999, "buy", decided_at=T1) is False  # unknown id
    p = load_pitches(db)[0]
    assert (p["status"], p["decided_at"]) == ("buy", T1)


def test_decide_pitch_rejects_unknown_action(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _pitch_row(db)
    assert decide_pitch(db, pitch_id, "explode", decided_at=T1) is False
    assert load_pitches(db)[0]["status"] == "open"


def test_last_pitch_at_per_ticker(tmp_path):
    db = str(tmp_path / "inbox.db")
    init_inbox_db(db)
    assert last_pitch_at(db, "EXE") is None
    _pitch_row(db, created_at=T0)
    _pitch_row(db, created_at=T1)
    assert last_pitch_at(db, "EXE") == T1
    assert last_pitch_at(db, "OTHER") is None


def test_set_message_id_round_trip(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _pitch_row(db)
    set_message_id(db, pitch_id, 555)
    assert load_pitches(db)[0]["telegram_message_id"] == 555
