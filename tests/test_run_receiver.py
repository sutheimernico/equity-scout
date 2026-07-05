"""Receiver loop: canned updates -> inbox decisions + telegram acks (all fakes)."""
from __future__ import annotations

from equity_scout.inbox_storage import create_pitch, load_pitches, set_message_id
from scripts.run_receiver import process_round

NOW = "2026-07-05T13:00:00+00:00"


def _seed_pitch(db: str) -> int:
    pitch_id = create_pitch(
        db, ticker="EXE", watchlist_id=1, price=90.0, composite=0.6,
        zone_low=85.0, zone_high=95.0, pitch="Pitch", created_at=NOW,
    )
    set_message_id(db, pitch_id, 777)
    return pitch_id


def _update(update_id: int, data: str, chat_id: int = 42) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {"id": f"cb{update_id}", "from": {"id": chat_id}, "data": data},
    }


def test_process_round_records_decision_and_acks(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _seed_pitch(db)
    acks: list[tuple[str, str]] = []
    edits: list[tuple[int, str]] = []

    offset = process_round(
        db,
        fetch=lambda offset: [_update(10, f"buy:{pitch_id}")],
        chat_id=42,
        offset=None,
        answer=lambda cb_id, text: acks.append((cb_id, text)),
        edit=lambda message_id, text: edits.append((message_id, text)),
        now=NOW,
    )
    assert offset == 11
    pitch = load_pitches(db)[0]
    assert (pitch["status"], pitch["decided_at"]) == ("buy", NOW)
    assert acks == [("cb10", "✅ Kaufen vermerkt")]
    assert edits and edits[0][0] == 777 and "✅ Kaufen" in edits[0][1]


def test_process_round_acks_already_decided_without_overwriting(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _seed_pitch(db)
    acks: list[tuple[str, str]] = []
    process_round(
        db, fetch=lambda o: [_update(10, f"buy:{pitch_id}")], chat_id=42, offset=None,
        answer=lambda cb_id, text: acks.append((cb_id, text)), edit=lambda m, t: None, now=NOW,
    )
    process_round(
        db, fetch=lambda o: [_update(11, f"pass:{pitch_id}")], chat_id=42, offset=None,
        answer=lambda cb_id, text: acks.append((cb_id, text)), edit=lambda m, t: None, now=NOW,
    )
    assert load_pitches(db)[0]["status"] == "buy"  # first decision wins
    assert acks[1][1] == "Bereits entschieden."


def test_process_round_ignores_foreign_and_malformed_updates(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _seed_pitch(db)
    offset = process_round(
        db,
        fetch=lambda o: [
            _update(20, f"buy:{pitch_id}", chat_id=999),  # wrong sender
            {"update_id": 21},  # malformed
            _update(22, "buy:12345"),  # unknown pitch
        ],
        chat_id=42, offset=None, answer=lambda c, t: None, edit=lambda m, t: None, now=NOW,
    )
    assert offset == 23
    assert load_pitches(db)[0]["status"] == "open"
