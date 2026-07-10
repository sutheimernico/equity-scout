"""Digest rendering (pure) + SMTP send behind a fake transport."""
from __future__ import annotations

import sys

from equity_scout.digest import build_digest, load_smtp_config, send_digest

PITCHES = [
    {"id": 1, "ticker": "EXE", "status": "open", "composite": 0.59, "price": 90.72,
     "created_at": "2026-07-05T10:00:00+00:00", "decided_at": None},
    {"id": 2, "ticker": "ABC", "status": "buy", "composite": 0.51, "price": 55.0,
     "created_at": "2026-07-04T10:00:00+00:00", "decided_at": "2026-07-05T09:00:00+00:00"},
]


def test_build_digest_lists_open_and_decided():
    text = build_digest(PITCHES, date_label="2026-07-05")
    assert "EXE" in text and "offen" in text.lower()
    assert "Offene Pitches: 1" in text  # count style dodges singular/plural agreement
    assert "ABC" in text and "✅" in text
    assert "Keine Anlageberatung" in text


def test_build_digest_decided_since_window_pins_line_and_drops_old():
    """The decided section is a daily digest, not a lifetime archive: only decisions at or
    after decided_since appear, and the rendered line is pinned exactly."""
    pitches = PITCHES + [
        {"id": 3, "ticker": "OLD", "status": "pass", "composite": 0.4, "price": 10.0,
         "created_at": "2026-06-30T10:00:00+00:00", "decided_at": "2026-07-01T09:00:00+00:00"},
    ]
    text = build_digest(
        pitches, date_label="2026-07-05", decided_since="2026-07-04T12:00:00+00:00"
    )
    assert "  ✅ Kaufentscheidung — ABC · am 2026-07-05" in text
    assert "OLD" not in text


def test_build_digest_empty_state():
    text = build_digest([], date_label="2026-07-05")
    # NOTE: the plan's draft asserted the mixed-case substring "keine offenen Pitches"
    # against text.lower() — that can never match an all-lowercased string. Fixed to
    # an all-lowercase needle (deviation noted per plan instructions).
    assert "keine offenen pitches" in text.lower()


def test_load_smtp_config_fail_safe(capsys):
    assert load_smtp_config({}) is None
    env = {
        "SMTP_HOST": "h", "SMTP_PORT": "465", "SMTP_USER": "u",
        "SMTP_PASSWORD": "p", "DIGEST_TO": "a@b.c",
    }
    cfg = load_smtp_config(env)
    assert cfg == {"host": "h", "port": 465, "user": "u", "password": "p", "to": "a@b.c"}
    bad = dict(env, SMTP_PORT="nope")
    assert load_smtp_config(bad) is None
    assert "SMTP_PORT" in capsys.readouterr().err


def test_send_digest_uses_transport_seam():
    sent: list[dict] = []

    class FakeSMTP:
        def __init__(self, host, port):
            sent.append({"connect": (host, port)})

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, password):
            sent.append({"login": user})

        def send_message(self, msg):
            sent.append({"subject": msg["Subject"], "to": msg["To"]})

    cfg = {"host": "h", "port": 465, "user": "u", "password": "p", "to": "a@b.c"}
    send_digest(cfg, "Betreff", "Text", smtp_factory=FakeSMTP)
    assert {"connect": ("h", 465)} in sent
    assert any("Betreff" == e.get("subject") for e in sent)


def test_main_without_smtp_config_prints_digest_and_exits_0(tmp_path, monkeypatch, capsys):
    from equity_scout.inbox_storage import create_pitch
    from scripts.run_digest import main

    db = str(tmp_path / "inbox.db")
    create_pitch(
        db, ticker="EXE", watchlist_id=1, price=90.72, composite=0.59,
        zone_low=85.0, zone_high=95.0, pitch="Pitch", created_at="2026-07-05T10:00:00+00:00",
    )
    for var in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "argv", ["run_digest.py", "--db", db])

    assert main() == 0
    out = capsys.readouterr().out
    assert "EXE" in out
    assert "SMTP not configured" in out


def test_build_digest_appends_measured_evidence_stats():
    stats = {
        "congress": {"n_resolved": 4, "n_open": 3, "hit_rate": 0.5,
                     "mean_relative_return": 0.012},
        "thirteen_f": {"n_resolved": 0, "n_open": 2, "hit_rate": None,
                       "mean_relative_return": None},
    }
    text = build_digest([], date_label="2026-07-10", evidence_stats=stats)
    assert "Evidenz-Quellen — gemessene Trefferquote vs SPY" in text
    assert "Kongress-Käufe: 4 aufgelöst, Trefferquote 50 %, Ø relative Rendite +1.2 % · offen: 3" in text
    # Unresolved sources state the absence instead of inventing numbers.
    assert "13F-Fonds: noch nichts aufgelöst · offen: 2" in text


def test_build_digest_omits_evidence_section_when_empty():
    assert "Evidenz-Quellen" not in build_digest([], date_label="2026-07-10")
    assert "Evidenz-Quellen" not in build_digest(
        [], date_label="2026-07-10", evidence_stats={}
    )
