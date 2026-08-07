"""Inbox storage: pitch lifecycle + cooldown lookups (tmp_path SQLite)."""
from __future__ import annotations

from equity_scout.inbox_storage import (
    create_pitch,
    decide_pitch,
    expire_stale_pitches,
    get_pitch,
    init_inbox_db,
    last_pitch_at,
    load_pitches,
    set_message_id,
)

T0 = "2026-07-05T10:00:00+00:00"
T1 = "2026-07-05T11:00:00+00:00"


def _pitch_row(db, ticker="EXE", created_at=T0, verdict="yellow"):
    # verdict defaults to a rated pitch — every pitch since v8 carries one; pass
    # verdict=None to model the pre-v8 legacy rows expire_stale_pitches withdraws.
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
        verdict=verdict,
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


def test_expire_stale_pitches_withdraws_only_open_offlist_rows(tmp_path):
    db = str(tmp_path / "inbox.db")
    on_list = _pitch_row(db, ticker="AAA")
    off_open = _pitch_row(db, ticker="GONE")
    off_decided = _pitch_row(db, ticker="OLD")
    decide_pitch(db, off_decided, "pass", decided_at=T0)

    expired = expire_stale_pitches(db, ["AAA", "BBB"], expired_at=T1)
    assert expired == 1

    rows = {p["id"]: p for p in load_pitches(db)}
    assert rows[on_list]["status"] == "open"  # still watched -> stays open
    assert rows[off_open]["status"] == "expired"
    assert rows[off_open]["decided_at"] == T1  # timestamp of the withdrawal
    assert rows[off_decided]["status"] == "pass"  # a made decision is never rewritten


def test_expire_stale_pitches_empty_watchlist_skips_the_offlist_rule(tmp_path):
    # A broken radar run (no entries) must never wipe the whole inbox in one sweep.
    db = str(tmp_path / "inbox.db")
    _pitch_row(db, ticker="AAA")
    assert expire_stale_pitches(db, [], expired_at=T1) == 0
    assert load_pitches(db)[0]["status"] == "open"


def test_expire_stale_pitches_withdraws_unrated_rows_even_on_the_watchlist(tmp_path):
    # Pre-v8 rows carry no verdict; an unrated offer is not decidable (Nico 2026-08-07)
    # — withdrawn regardless of watchlist membership, and independent of the empty-list
    # guard above.
    db = str(tmp_path / "inbox.db")
    unrated = _pitch_row(db, ticker="AAA", verdict=None)
    rated = _pitch_row(db, ticker="AAA")
    assert expire_stale_pitches(db, [], expired_at=T1) == 1
    rows = {p["id"]: p for p in load_pitches(db)}
    assert rows[unrated]["status"] == "expired"
    assert rows[rated]["status"] == "open"


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


def test_get_pitch_by_id(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _pitch_row(db)
    p = get_pitch(db, pitch_id)
    assert p is not None
    assert (p["id"], p["ticker"], p["status"]) == (pitch_id, "EXE", "open")
    assert get_pitch(db, 999) is None  # unknown id
    assert get_pitch(db, -1) is None  # bounds guard, same as decide_pitch
    assert get_pitch(db, 2**63) is None
    assert get_pitch(str(tmp_path / "fresh.db"), 1) is None  # self-init, no crash
