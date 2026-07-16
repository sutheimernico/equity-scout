"""Receiver loop: canned updates -> inbox decisions + telegram acks (all fakes)."""
from __future__ import annotations

import sys
import time

import scripts.run_receiver as run_receiver_mod
from equity_scout.inbox_storage import create_pitch, load_pitches, set_message_id
from equity_scout.telegram_client import TelegramError
from scripts.run_receiver import main, process_round

NOW = "2026-07-05T13:00:00+00:00"
LATER = "2026-07-05T14:00:00+00:00"


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


def test_process_round_survives_answer_and_edit_failures(tmp_path, capsys):
    """A failing ack or edit must never lose the decision or abort the round."""
    db = str(tmp_path / "inbox.db")
    pitch_id = _seed_pitch(db)

    def bad_answer(cb_id, text):
        raise TelegramError("answerCallbackQuery failed: query is too old")

    def bad_edit(message_id, text):
        raise TelegramError("editMessageText failed: message to edit not found")

    offset = process_round(
        db, fetch=lambda o: [_update(10, f"buy:{pitch_id}")], chat_id=42, offset=None,
        answer=bad_answer, edit=bad_edit, now=NOW,
    )
    assert offset == 11
    pitch = load_pitches(db)[0]
    assert (pitch["status"], pitch["decided_at"]) == ("buy", NOW)  # decision survived
    err = capsys.readouterr().err
    assert "Warnung" in err and "fehlgeschlagen" in err


def test_duplicate_press_on_decided_pitch_reattempts_edit(tmp_path):
    """Self-heal: if the outcome edit was lost, a duplicate tap re-attempts it with the
    ORIGINAL decision's label and timestamp (idempotent — Telegram no-ops if unchanged)."""
    db = str(tmp_path / "inbox.db")
    pitch_id = _seed_pitch(db)

    def lost_edit(message_id, text):
        raise TelegramError("editMessageText failed: flaky")

    process_round(
        db, fetch=lambda o: [_update(10, f"buy:{pitch_id}")], chat_id=42, offset=None,
        answer=lambda c, t: None, edit=lost_edit, now=NOW,
    )
    acks: list[tuple[str, str]] = []
    edits: list[tuple[int, str]] = []
    process_round(
        db, fetch=lambda o: [_update(11, f"pass:{pitch_id}")], chat_id=42, offset=None,
        answer=lambda cb_id, text: acks.append((cb_id, text)),
        edit=lambda message_id, text: edits.append((message_id, text)),
        now=LATER,
    )
    assert load_pitches(db)[0]["status"] == "buy"  # duplicate press never overwrites
    assert acks == [("cb11", "Bereits entschieden.")]
    assert edits and edits[0][0] == 777
    assert "✅ Kaufen" in edits[0][1] and NOW in edits[0][1]  # original decision + its timestamp


def test_detail_press_sends_stored_html_and_keeps_pitch_open(tmp_path):
    """🔎 Details replies with the stored HTML long pitch; it is NOT a decision."""
    db = str(tmp_path / "inbox.db")
    pitch_id = create_pitch(
        db, ticker="EXE", watchlist_id=1, price=90.0, composite=0.6,
        zone_low=85.0, zone_high=95.0, pitch="Plain", created_at=NOW,
        pitch_html="<b>EXE</b>\n\n<blockquote expandable>Tiefe</blockquote>",
    )
    set_message_id(db, pitch_id, 777)
    acks: list[tuple[str, str]] = []
    details: list[tuple[str, str | None]] = []

    process_round(
        db, fetch=lambda o: [_update(10, f"detail:{pitch_id}")], chat_id=42, offset=None,
        answer=lambda cb_id, text: acks.append((cb_id, text)),
        edit=lambda m, t: None,
        send_detail=lambda text, mode: details.append((text, mode)),
        now=NOW,
    )
    assert load_pitches(db)[0]["status"] == "open"  # still decidable afterwards
    assert acks == [("cb10", "Details folgen.")]
    assert details == [("<b>EXE</b>\n\n<blockquote expandable>Tiefe</blockquote>", "HTML")]


def test_detail_press_falls_back_to_plain_for_pre_v8_rows(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _seed_pitch(db)  # no pitch_html
    details: list[tuple[str, str | None]] = []

    process_round(
        db, fetch=lambda o: [_update(10, f"detail:{pitch_id}")], chat_id=42, offset=None,
        answer=lambda c, t: None, edit=lambda m, t: None,
        send_detail=lambda text, mode: details.append((text, mode)),
        now=NOW,
    )
    assert details == [("Pitch", None)]


def test_detail_press_on_unknown_pitch_answers_politely(tmp_path):
    db = str(tmp_path / "inbox.db")
    _seed_pitch(db)
    acks: list[tuple[str, str]] = []
    details: list[tuple[str, str | None]] = []

    process_round(
        db, fetch=lambda o: [_update(10, "detail:12345")], chat_id=42, offset=None,
        answer=lambda cb_id, text: acks.append((cb_id, text)), edit=lambda m, t: None,
        send_detail=lambda text, mode: details.append((text, mode)),
        now=NOW,
    )
    assert acks == [("cb10", "Pitch nicht gefunden.")]
    assert details == []


def test_main_survives_round_errors_with_backoff(tmp_path, monkeypatch, capsys):
    """A dead network must not kill the unattended loop: warn, back off 5s, keep polling."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    def down(token, offset):
        raise TelegramError("getUpdates failed: network unreachable")

    monkeypatch.setattr(run_receiver_mod, "get_updates", down)
    monkeypatch.setenv("COPILOT_TG_BOT_TOKEN", "t")
    monkeypatch.setenv("COPILOT_TG_CHAT_ID", "42")
    db = str(tmp_path / "inbox.db")
    monkeypatch.setattr(sys, "argv", ["run_receiver.py", "--db", db, "--rounds", "2"])

    assert main() == 0
    assert sleeps == [5, 5]
    err = capsys.readouterr().err
    assert "Warnung" in err and "fehlgeschlagen" in err
