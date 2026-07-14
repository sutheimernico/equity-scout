"""Candidate selection rules + notify orchestration with fakes end-to-end."""
from __future__ import annotations

import sys

import scripts.run_notify as run_notify_mod
from equity_scout.evidence.base import SOURCE_CONGRESS, EvidenceEvent
from equity_scout.evidence.storage import load_alerts, record_events
from equity_scout.fundamentals import Fundamentals
from equity_scout.inbox_storage import create_pitch, load_pitches
from equity_scout.notify import notify_watchlist, select_candidates, send_evidence_alerts
from equity_scout.pitch import build_pitch
from equity_scout.radar import Watchlist, WatchlistEntry
from equity_scout.radar_storage import save_watchlist
from equity_scout.signals import SignalReading
from equity_scout.telegram_client import TelegramError
from scripts.run_notify import main

NOW = "2026-07-05T12:00:00+00:00"


def _no_fund(ticker: str) -> Fundamentals:
    """Offline enrich seam: never touches the network in tests."""
    return Fundamentals(None, None, None, None)


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


def test_select_candidates_repitches_exactly_at_cooldown_boundary():
    """last pitch EXACTLY cooldown_days ago -> the boundary day is free again (strict `<`)."""
    watchlist = {"created_at": NOW, "entries": [_entry("EDGE")]}
    picked = select_candidates(
        watchlist,
        last_pitch_at=lambda t: "2026-06-28T12:00:00+00:00",  # NOW minus exactly 7 days
        threshold=0.45,
        cooldown_days=7,
        now=NOW,
    )
    assert [e["ticker"] for e in picked] == ["EDGE"]


def test_notify_watchlist_creates_pitches_and_sends(tmp_path):
    db = str(tmp_path / "inbox.db")
    watchlist = {
        "created_at": NOW,
        "watchlist_id": 77,  # injected by radar_storage.load_latest_watchlist
        "entries": [_entry("YES"), _entry("LOW", composite=0.1)],
    }
    sent: list[tuple[int, str]] = []

    def fake_send(pitch_id: int, text: str, entry: dict, fundamentals) -> int:
        assert entry["ticker"]  # sender gets the entry for the chart-photo variant
        sent.append((pitch_id, text))
        return 500 + pitch_id

    count = notify_watchlist(
        db,
        watchlist,
        build=lambda entry, fund: f"PITCH {entry['ticker']}",
        send=fake_send,
        enrich=_no_fund,
        threshold=0.45,
        cooldown_days=7,
        now=NOW,
    )
    assert count == 1
    pitches = load_pitches(db)
    assert len(pitches) == 1
    assert pitches[0]["ticker"] == "YES"
    # The pitch row is FK'd to the top-level snapshot id, not a per-entry field.
    assert pitches[0]["watchlist_id"] == 77
    # Pin the zone mapping field-by-field: entry_zone_low -> zone_low and
    # entry_zone_high -> zone_high; a swap in the create_pitch call must fail here.
    assert pitches[0]["zone_low"] == 95.0
    assert pitches[0]["zone_high"] == 105.0
    # fake_send returns 500 + pitch_id; the plan's original assertion
    # (`501 + id - 1`) was an awkward way of writing the same identity.
    assert pitches[0]["telegram_message_id"] == 500 + pitches[0]["id"]
    assert sent == [(pitches[0]["id"], "PITCH YES")]


def test_notify_watchlist_continues_after_telegram_error(tmp_path, capsys):
    """A failed send must not abort the batch: the row keeps message_id NULL, a
    German warning goes to stderr, and later candidates are still pitched + sent."""
    db = str(tmp_path / "inbox.db")
    watchlist = {"created_at": NOW, "entries": [_entry("BOOM"), _entry("OKAY")]}
    sent: list[int] = []

    def flaky_send(pitch_id: int, text: str, entry: dict, fundamentals) -> int:
        if "BOOM" in text:
            raise TelegramError("chat not found")
        sent.append(pitch_id)
        return 900 + pitch_id

    count = notify_watchlist(
        db,
        watchlist,
        build=lambda entry, fund: f"PITCH {entry['ticker']}",
        send=flaky_send,
        enrich=_no_fund,
        threshold=0.45,
        cooldown_days=7,
        now=NOW,
    )
    assert count == 2
    assert "Warnung: Telegram-Versand für BOOM fehlgeschlagen" in capsys.readouterr().err
    by_ticker = {p["ticker"]: p for p in load_pitches(db)}
    assert by_ticker["BOOM"]["telegram_message_id"] is None  # row survives the failed send
    assert by_ticker["OKAY"]["telegram_message_id"] == 900 + by_ticker["OKAY"]["id"]
    assert sent == [by_ticker["OKAY"]["id"]]


def test_notify_watchlist_without_send_still_creates_inbox_rows(tmp_path):
    db = str(tmp_path / "inbox.db")
    watchlist = {"created_at": NOW, "entries": [_entry("YES")]}
    count = notify_watchlist(
        db, watchlist, build=lambda e, f: "P", send=None, enrich=_no_fund,
        threshold=0.45, cooldown_days=7, now=NOW,
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
        db, watchlist, build=lambda e, f: "P", send=None, enrich=_no_fund,
        threshold=0.45, cooldown_days=7, now=NOW,
    )
    assert count == 0


def _build_with_stub_llm(entry, fundamentals):
    """Real pitch layout, injected offline LLM seam so the notify path stays network-free."""
    return build_pitch(entry, fundamentals, ask=lambda question, context: "stub")


def test_notify_watchlist_enriches_pitch_with_analyst_consensus(tmp_path):
    """Task 4: a fake enrich feeds each candidate's fundamentals into the pitch — the
    stored pitch carries the third-party analyst line, and enrich runs once per candidate."""
    db = str(tmp_path / "inbox.db")
    watchlist = {"created_at": NOW, "entries": [_entry("YES"), _entry("ALSO")]}
    calls: list[str] = []

    def fake_enrich(ticker: str) -> Fundamentals:
        calls.append(ticker)
        return Fundamentals(trailing_pe=18.4, analyst_target=120.0, analyst_count=8, currency="USD")

    count = notify_watchlist(
        db, watchlist, build=_build_with_stub_llm, send=None, enrich=fake_enrich,
        threshold=0.45, cooldown_days=7, now=NOW,
    )
    assert count == 2
    assert calls == ["YES", "ALSO"]  # fetched once per candidate, in order
    pitch = {p["ticker"]: p["pitch"] for p in load_pitches(db)}["YES"]
    assert "Analystensicht: Ø-Kursziel 120.00 USD (8 Schätzungen)" in pitch


def test_notify_watchlist_renders_honest_absence_when_enrich_is_empty(tmp_path):
    """All-None fundamentals -> the honest-absence line, never a fabricated target."""
    db = str(tmp_path / "inbox.db")
    watchlist = {"created_at": NOW, "entries": [_entry("YES")]}
    count = notify_watchlist(
        db, watchlist, build=_build_with_stub_llm, send=None, enrich=_no_fund,
        threshold=0.45, cooldown_days=7, now=NOW,
    )
    assert count == 1
    pitch = load_pitches(db)[0]["pitch"]
    assert "keine Schätzung verfügbar" in pitch
    assert "Ø-Kursziel" not in pitch


def _seed_watchlist_db(db: str, ticker: str = "YES", composite: float = 0.6) -> int:
    """Seed a saved watchlist via radar_storage, matching the run_radar CLI-test idiom.
    Returns the snapshot row id."""
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
    return save_watchlist(db, Watchlist(created_at=NOW, entries=[entry]))


def _evidence_event(ticker: str, politician: str, event_date: str) -> EvidenceEvent:
    return EvidenceEvent(
        source=SOURCE_CONGRESS,
        ticker=ticker,
        event_key=f"{politician}-{event_date}",
        event_date=event_date,
        details={"politician": politician, "filing_date": event_date},
    )


def _cluster(ticker: str, *politicians: str, event_date: str = "2026-07-01") -> dict:
    return {
        ticker: [
            {
                "source": SOURCE_CONGRESS,
                "ticker": ticker,
                "event_key": f"{p}-{event_date}",
                "event_date": event_date,
                "details": {"politician": p, "filing_date": event_date},
            }
            for p in politicians
        ]
    }


def test_send_evidence_alerts_records_before_send_and_sets_message_id(tmp_path):
    db = str(tmp_path / "alerts.db")
    sent: list[str] = []

    def fake_send(text: str) -> int:
        sent.append(text)
        return 4711

    count = send_evidence_alerts(
        db, _cluster("EXE", "Jane Doe", "John Roe"), send=fake_send, now=NOW
    )
    assert count == 1
    alerts = load_alerts(db)
    assert len(alerts) == 1
    assert alerts[0]["ticker"] == "EXE"
    assert alerts[0]["reasons"] == ["2 Kongress-Mitglieder haben gekauft"]
    assert alerts[0]["telegram_message_id"] == 4711
    assert sent and "kein Screener-Pick" in sent[0]


def test_send_evidence_alerts_survives_telegram_error(tmp_path, capsys):
    db = str(tmp_path / "alerts.db")

    def boom(text: str) -> int:
        raise TelegramError("chat not found")

    count = send_evidence_alerts(
        db, _cluster("EXE", "Jane Doe", "John Roe"), send=boom, now=NOW
    )
    assert count == 1  # the row is the source of truth; the send is best-effort
    assert "Evidenz-Alarm EXE fehlgeschlagen" in capsys.readouterr().err
    assert load_alerts(db)[0]["telegram_message_id"] is None


def test_send_evidence_alerts_respects_cooldown(tmp_path):
    db = str(tmp_path / "alerts.db")
    clusters = _cluster("EXE", "Jane Doe", "John Roe")
    assert send_evidence_alerts(db, clusters, send=None, now=NOW) == 1
    # Second run inside the 14-day window: same cluster, no new row.
    assert send_evidence_alerts(db, clusters, send=None, now=NOW) == 0
    assert len(load_alerts(db)) == 1
    # After the cooldown the accumulated facts may re-alert.
    later = "2026-07-20T12:00:00+00:00"
    assert send_evidence_alerts(db, clusters, send=None, now=later) == 1


def test_send_evidence_alerts_without_sender_records_rows_only(tmp_path):
    db = str(tmp_path / "alerts.db")
    count = send_evidence_alerts(
        db, _cluster("EXE", "Jane Doe", "John Roe"), send=None, now=NOW
    )
    assert count == 1
    assert load_alerts(db)[0]["telegram_message_id"] is None


def test_send_evidence_alerts_ignores_single_buyer_noise(tmp_path):
    db = str(tmp_path / "alerts.db")
    assert send_evidence_alerts(db, _cluster("EXE", "Jane Doe"), send=None, now=NOW) == 0
    assert load_alerts(db) == []


def test_send_evidence_alerts_escalates_past_cooldown_when_buyers_grow(tmp_path):
    """F4: a 2-buyer alert must not silence the 4-buyer cluster that follows inside
    the same 14-day cooldown window — the cluster genuinely grew."""
    db = str(tmp_path / "alerts.db")
    small = _cluster("EXE", "Jane Doe", "John Roe")
    assert send_evidence_alerts(db, small, send=None, now=NOW) == 1

    grown = _cluster("EXE", "Jane Doe", "John Roe", "Ada Lee", "Max Roe")
    assert send_evidence_alerts(db, grown, send=None, now=NOW) == 1  # breaks the cooldown

    alerts = load_alerts(db)
    assert len(alerts) == 2
    assert alerts[0]["buyer_count"] == 4  # newest-first
    assert "Eskalation" in alerts[0]["text"]
    assert alerts[1]["buyer_count"] == 2
    assert "Eskalation" not in alerts[1]["text"]


def test_send_evidence_alerts_same_buyer_count_stays_suppressed_in_cooldown(tmp_path):
    """A repeat of the SAME cluster (no growth) must stay suppressed — only a genuine
    rise in distinct buyers overrides the cooldown, not a mere re-collection."""
    db = str(tmp_path / "alerts.db")
    cluster = _cluster("EXE", "Jane Doe", "John Roe")
    assert send_evidence_alerts(db, cluster, send=None, now=NOW) == 1
    assert send_evidence_alerts(db, cluster, send=None, now=NOW) == 0
    assert len(load_alerts(db)) == 1


def test_main_writes_inbox_only_without_telegram_config(tmp_path, monkeypatch, capsys):
    """No COPILOT_TG_* env -> inbox-only path, exit 0, no network attempted."""
    db = str(tmp_path / "run.db")
    snapshot_id = _seed_watchlist_db(db)
    monkeypatch.delenv("COPILOT_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("COPILOT_TG_CHAT_ID", raising=False)
    # build_pitch's default `ask` seam calls the (possibly unreachable) local Ollama
    # server and enrich hits yfinance; fake both so this CLI test never touches the network.
    monkeypatch.setattr(
        run_notify_mod,
        "build_pitch",
        lambda entry, fund, evidence=None: f"PITCH {entry['ticker']}",
    )
    monkeypatch.setattr(run_notify_mod, "fetch_fundamentals", _no_fund)
    monkeypatch.setattr(sys, "argv", ["run_notify.py", "--db", db])

    assert main() == 0

    out = capsys.readouterr().out
    assert "Telegram not configured" in out
    assert "Pitches created: 1." in out
    pitches = load_pitches(db)
    assert len(pitches) == 1
    assert pitches[0]["ticker"] == "YES"
    assert pitches[0]["telegram_message_id"] is None
    # Through the REAL path (save -> load_latest -> notify) the pitch row must be
    # FK'd to the watchlist snapshot it came from — never NULL.
    assert pitches[0]["watchlist_id"] == snapshot_id


def test_main_dry_run_never_sends_even_with_telegram_config(tmp_path, monkeypatch, capsys):
    """--dry-run with full COPILOT_TG_* config -> inbox-only; send_message must never run."""
    db = str(tmp_path / "run.db")
    _seed_watchlist_db(db)
    monkeypatch.setenv("COPILOT_TG_BOT_TOKEN", "test-token")
    monkeypatch.setenv("COPILOT_TG_CHAT_ID", "4242")

    def fail_loudly(*args, **kwargs):
        raise AssertionError("send_message must not be called with --dry-run")

    monkeypatch.setattr(run_notify_mod, "send_message", fail_loudly)
    monkeypatch.setattr(
        run_notify_mod,
        "build_pitch",
        lambda entry, fund, evidence=None: f"PITCH {entry['ticker']}",
    )
    monkeypatch.setattr(run_notify_mod, "fetch_fundamentals", _no_fund)
    monkeypatch.setattr(sys, "argv", ["run_notify.py", "--db", db, "--dry-run"])

    assert main() == 0

    out = capsys.readouterr().out
    assert "Telegram not configured" in out  # dry-run reuses the inbox-only message
    assert "Pitches created: 1." in out
    pitches = load_pitches(db)
    assert len(pitches) == 1
    assert pitches[0]["telegram_message_id"] is None


def test_main_exits_1_without_watchlist(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "fresh.db")
    monkeypatch.delenv("COPILOT_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("COPILOT_TG_CHAT_ID", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_notify.py", "--db", db])

    assert main() == 1
    assert "No watchlist found" in capsys.readouterr().err


def test_main_annotates_pitches_with_evidence_and_alerts_off_watchlist(
    tmp_path, monkeypatch, capsys
):
    """Wiring test: watchlist-ticker evidence reaches build_pitch; an off-watchlist
    congress cluster becomes exactly one alert row. main() uses the real clock, so
    the seeded events are dated relative to today (test setup only — never prod)."""
    from datetime import datetime, timezone

    db = str(tmp_path / "run.db")
    _seed_watchlist_db(db)  # watchlist ticker: YES
    today = datetime.now(timezone.utc).date().isoformat()
    record_events(
        db,
        [
            _evidence_event("YES", "Jane Doe", today),
            _evidence_event("OFFW", "Jane Doe", today),
            _evidence_event("OFFW", "John Roe", today),
        ],
        now=f"{today}T00:00:00+00:00",
    )
    monkeypatch.delenv("COPILOT_TG_BOT_TOKEN", raising=False)
    monkeypatch.delenv("COPILOT_TG_CHAT_ID", raising=False)
    monkeypatch.setattr(
        run_notify_mod,
        "build_pitch",
        lambda entry, fund, evidence=None: f"PITCH {entry['ticker']} ev={len(evidence or [])}",
    )
    monkeypatch.setattr(run_notify_mod, "fetch_fundamentals", _no_fund)
    monkeypatch.setattr(sys, "argv", ["run_notify.py", "--db", db])

    assert main() == 0

    out = capsys.readouterr().out
    assert "Pitches created: 1." in out
    assert "Evidenz-Alarme: 1." in out
    # The watchlist candidate's single congress event reached the pitch builder ...
    assert load_pitches(db)[0]["pitch"] == "PITCH YES ev=1"
    # ... and only the off-watchlist CLUSTER alerted (YES has one buyer -> no alert).
    alerts = load_alerts(db)
    assert [a["ticker"] for a in alerts] == ["OFFW"]


def test_select_candidates_tops_up_to_min_count():
    """min_count fills the daily batch with the best remaining names (Nico 2026-07-15:
    several pitches per daily), never re-pitching names inside their cooldown."""
    watchlist = {
        "created_at": NOW,
        "entries": [
            _entry("ZONE"),  # in zone, above threshold -> qualified
            {**_entry("BEST"), "in_zone": False, "composite": 0.95},
            {**_entry("GOOD"), "in_zone": False, "composite": 0.80},
            {**_entry("MEH"), "in_zone": False, "composite": 0.50},
            {**_entry("COOL"), "in_zone": False, "composite": 0.99},  # in cooldown
        ],
    }
    picked = select_candidates(
        watchlist,
        last_pitch_at=lambda t: NOW if t == "COOL" else None,
        threshold=0.45, cooldown_days=7, now=NOW, min_count=3,
    )
    assert [entry["ticker"] for entry in picked] == ["ZONE", "BEST", "GOOD"]


def test_select_candidates_min_count_zero_is_unchanged():
    watchlist = {"created_at": NOW,
                 "entries": [{**_entry("OFF"), "in_zone": False, "composite": 0.99}]}
    assert select_candidates(
        watchlist, last_pitch_at=lambda t: None,
        threshold=0.45, cooldown_days=7, now=NOW,
    ) == []
