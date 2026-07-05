"""Candidate selection rules + notify orchestration with fakes end-to-end."""
from __future__ import annotations

import sys

import scripts.run_notify as run_notify_mod
from equity_scout.inbox_storage import create_pitch, load_pitches
from equity_scout.notify import notify_watchlist, select_candidates
from equity_scout.radar import Watchlist, WatchlistEntry
from equity_scout.radar_storage import save_watchlist
from equity_scout.signals import SignalReading
from scripts.run_notify import main

NOW = "2026-07-05T12:00:00+00:00"


def _entry(ticker: str, composite: float = 0.6, in_zone: bool = True) -> dict:
    return {
        "ticker": ticker,
        "name": f"{ticker} Corp",
        "bucket": "core",
        "price": 100.0,
        "entry_zone_low": 95.0,
        "entry_zone_high": 105.0,
        "in_zone": in_zone,
        "proximity": -0.05,
        "composite": composite,
        "zone_note": "Kurs in der Entry-Zone (95.00–105.00).",
        "breakdown": {"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5},
        "readings": [{"name": "dip_quality", "score": 0.5, "reason": "Grund."}],
    }


def test_select_candidates_filters_zone_threshold_cooldown():
    watchlist = {
        "created_at": NOW,
        "entries": [
            _entry("YES"),
            _entry("COLD"),
            _entry("LOW", composite=0.2),
            _entry("OUT", in_zone=False),
        ],
    }
    picked = select_candidates(
        watchlist,
        last_pitch_at=lambda t: "2026-07-04T12:00:00+00:00" if t == "COLD" else None,
        threshold=0.45,
        cooldown_days=7,
        now=NOW,
    )
    assert [e["ticker"] for e in picked] == ["YES"]


def test_select_candidates_repitches_after_cooldown():
    watchlist = {"created_at": NOW, "entries": [_entry("COLD")]}
    picked = select_candidates(
        watchlist,
        last_pitch_at=lambda t: "2026-06-20T12:00:00+00:00",
        threshold=0.45,
        cooldown_days=7,
        now=NOW,
    )
    assert [e["ticker"] for e in picked] == ["COLD"]


def test_notify_watchlist_creates_pitches_and_sends(tmp_path):
    db = str(tmp_path / "inbox.db")
    watchlist = {"created_at": NOW, "entries": [_entry("YES"), _entry("LOW", composite=0.1)]}
    sent: list[tuple[int, str]] = []

    def fake_send(pitch_id: int, text: str) -> int:
        sent.append((pitch_id, text))
        return 500 + pitch_id

    count = notify_watchlist(
        db,
        watchlist,
        build=lambda entry: f"PITCH {entry['ticker']}",
        send=fake_send,
        threshold=0.45,
        cooldown_days=7,
        now=NOW,
    )
    assert count == 1
    pitches = load_pitches(db)
    assert len(pitches) == 1
    assert pitches[0]["ticker"] == "YES"
    # fake_send returns 500 + pitch_id; the plan's original assertion
    # (`501 + id - 1`) was an awkward way of writing the same identity.
    assert pitches[0]["telegram_message_id"] == 500 + pitches[0]["id"]
    assert sent == [(pitches[0]["id"], "PITCH YES")]


def test_notify_watchlist_without_send_still_creates_inbox_rows(tmp_path):
    db = str(tmp_path / "inbox.db")
    watchlist = {"created_at": NOW, "entries": [_entry("YES")]}
    count = notify_watchlist(
        db, watchlist, build=lambda e: "P", send=None, threshold=0.45, cooldown_days=7, now=NOW
    )
    assert count == 1
    assert load_pitches(db)[0]["telegram_message_id"] is None


def test_notify_respects_cooldown_from_own_previous_run(tmp_path):
    db = str(tmp_path / "inbox.db")
    create_pitch(
        db, ticker="YES", watchlist_id=None, price=1, composite=0.5, zone_low=1,
        zone_high=2, pitch="alt", created_at="2026-07-04T12:00:00+00:00",
    )
    watchlist = {"created_at": NOW, "entries": [_entry("YES")]}
    count = notify_watchlist(
        db, watchlist, build=lambda e: "P", send=None, threshold=0.45, cooldown_days=7, now=NOW
    )
    assert count == 0


def _seed_watchlist_db(db: str, ticker: str = "YES", composite: float = 0.6) -> None:
    """Seed a saved watchlist via radar_storage, matching the run_radar CLI-test idiom."""
    entry = WatchlistEntry(
        ticker=ticker,
        name=f"{ticker} Corp",
        bucket="core",
        price=100.0,
        entry_zone_low=95.0,
        entry_zone_high=105.0,
        proximity=-0.05,
        in_zone=True,
        composite=composite,
        readings=[SignalReading("dip_quality", 0.5, "Grund.")],
        zone_note="Kurs in der Entry-Zone (95.00–105.00).",
        breakdown={"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5},
    )
    save_watchlist(db, Watchlist(created_at=NOW, entries=[entry]))


def test_main_writes_inbox_only_without_telegram_config(tmp_path, monkeypatch, capsys):
    """No COPILOT_TG_* env -> inbox-only path, exit 0, no network attempted."""
    db = str(tmp_path / "run.db")
    _seed_watchlist_db(db)
    monkeypatch.delenv("COPILOT_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("COPILOT_TG_CHAT_ID", raising=False)
    # build_pitch's default `ask` seam calls the (possibly unreachable) local Ollama
    # server; fake it out so this CLI test never touches the network.
    monkeypatch.setattr(run_notify_mod, "build_pitch", lambda entry: f"PITCH {entry['ticker']}")
    monkeypatch.setattr(sys, "argv", ["run_notify.py", "--db", db])

    assert main() == 0

    out = capsys.readouterr().out
    assert "Telegram not configured" in out
    assert "Pitches created: 1." in out
    pitches = load_pitches(db)
    assert len(pitches) == 1
    assert pitches[0]["ticker"] == "YES"
    assert pitches[0]["telegram_message_id"] is None


def test_main_exits_1_without_watchlist(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "fresh.db")
    monkeypatch.delenv("COPILOT_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("COPILOT_TG_CHAT_ID", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_notify.py", "--db", db])

    assert main() == 1
    assert "No watchlist found" in capsys.readouterr().err
