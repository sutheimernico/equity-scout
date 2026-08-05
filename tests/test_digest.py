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
    assert "📬 1 Pitch offen" in text  # count carries the number, no plural agreement
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
    assert "✅ Entschieden: ✅ Kaufentscheidung ABC" in text
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
    # Channel split (2026-07-14): stdout is the fallback when BOTH delivery paths are off.
    for var in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO",
                "COPILOT_TG_BOT_TOKEN", "COPILOT_TG_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "argv", ["run_digest.py", "--db", db])

    assert main() == 0
    out = capsys.readouterr().out
    # The fixture pitch predates the 24h window, so it is counted but not listed
    # (2026-08-04 diet: only fresh pitches earn a line).
    assert "📬 1 Pitch offen · nichts neu" in out
    assert "Neither SMTP nor Telegram configured" in out


def test_build_digest_omits_evidence_line_when_empty():
    """See the condensed evidence tests below for the rendered one-line forms."""
    assert "🔬 Evidenz" not in build_digest([], date_label="2026-07-10")
    assert "🔬 Evidenz" not in build_digest(
        [], date_label="2026-07-10", evidence_stats={}
    )


def test_open_pitch_line_carries_stored_verdict():
    """v9: the digest is the daily main touchpoint — it must show the SAME verdict
    already persisted on the pitch (compute_verdict at notify time), not silently
    drop it behind a generic mailbox icon."""
    pitches = [{
        "ticker": "AIRT", "status": "open", "composite": 0.50, "price": 27.15,
        "created_at": "2026-07-16T19:00:00+00:00", "decided_at": None,
        "verdict": "red", "verdict_why": "Kurs +23.8 % über dem 200-Tage-Schnitt",
    }]
    text = build_digest(pitches, date_label="2026-07-19")
    assert "🔴 AIRT" in text
    # The verdict_why moved to the pitch message itself (2026-08-04 diet) — the digest
    # line carries the traffic light, the score and the price, nothing else.
    assert "200-Tage-Schnitt" not in text
    assert "📬 offen — AIRT" not in text


def test_open_pitch_without_verdict_falls_back_to_mailbox_icon():
    """Pre-v8 rows have no verdict columns (see test_verdict.py's migration test) —
    the digest must degrade honestly instead of crashing or inventing a verdict."""
    pitches = [{
        "ticker": "OLD", "status": "open", "composite": 0.50, "price": 10.0,
        "created_at": "2026-07-01T19:00:00+00:00", "decided_at": None,
    }]
    text = build_digest(pitches, date_label="2026-07-19")
    assert "📬 OLD" in text


def test_opportunities_render_live_verdict():
    """Opportunities (radar watchlist entries) carry the full entry shape (breakdown,
    readings) needed for compute_verdict — unlike the minimal fixtures in
    test_digest_sections.py, which stay defensive-fallback cases."""
    entry = {
        "ticker": "TST", "composite": 0.75, "in_zone": True, "value_gap": 0.0,
        "readings": [], "breakdown": {"value": 0.8, "momentum": 0.7},
    }
    text = build_digest([], date_label="2026-07-19", opportunities=[entry])
    assert "🎯 Chancen: TST 75" in text


def _open(ticker, created, verdict=None, composite=0.5):
    return {
        "ticker": ticker, "status": "open", "composite": composite, "price": 10.0,
        "created_at": created, "decided_at": None, "verdict": verdict,
        "verdict_why": None,
    }


def test_open_pitches_dedupe_keeps_newest_per_ticker():
    """Cooldown re-pitches otherwise pile up as duplicate lines for the same ticker."""
    pitches = [
        _open("AAA", "2026-07-10T10:00:00+00:00", "red"),
        _open("AAA", "2026-07-16T10:00:00+00:00", "green"),
    ]
    text = build_digest(pitches, date_label="2026-07-19")
    assert text.count("AAA") == 1
    assert "🟢 AAA" in text


def _pitch_lines(text: str) -> list[str]:
    """The rendered per-pitch lines (indented, '<icon> TICKER · NN/100 · price')."""
    return [ln for ln in text.splitlines() if ln.startswith("  ") and "/100 · " in ln]


def test_open_pitches_sorted_green_first_and_capped():
    pitches = [_open(f"T{i:02d}", f"2026-07-{10 + i:02d}T10:00:00+00:00", "red") for i in range(8)]
    pitches.append(_open("WIN", "2026-07-05T10:00:00+00:00", "green"))
    text = build_digest(pitches, date_label="2026-07-19")
    open_lines = _pitch_lines(text)
    assert len(open_lines) == 6
    assert "WIN" in open_lines[0]
    # The count in the head reports all nine; the cap only limits the listed lines.
    assert "📬 9 Pitches offen · 9 neu" in text


def test_open_pitch_line_is_icon_ticker_score_price():
    pitches = [_open("NOWHY", "2026-07-16T10:00:00+00:00", "yellow")]
    text = build_digest(pitches, date_label="2026-07-19")
    assert "  🟡 NOWHY · 50/100 · 10.00" in text


def test_open_pitches_exactly_at_cap_lists_all_six():
    pitches = [_open(f"T{i:02d}", f"2026-07-{10 + i:02d}T10:00:00+00:00", "red") for i in range(6)]
    text = build_digest(pitches, date_label="2026-07-19")
    assert len(_pitch_lines(text)) == 6


def test_open_pitches_over_cap_still_reports_the_full_count():
    pitches = [_open(f"T{i:02d}", f"2026-07-{10 + i:02d}T10:00:00+00:00", "red") for i in range(7)]
    text = build_digest(pitches, date_label="2026-07-19")
    assert len(_pitch_lines(text)) == 6
    assert "📬 7 Pitches offen" in text


def test_open_pitches_newest_first_within_verdict_band():
    """Guards the reverse=True in _dedupe_open's second sort — a stable sort with the
    wrong direction there would silently flip newest/oldest within a band."""
    pitches = [
        _open("OLDER", "2026-07-10T10:00:00+00:00", "red"),
        _open("NEWER", "2026-07-16T10:00:00+00:00", "red"),
    ]
    text = build_digest(pitches, date_label="2026-07-19")
    open_lines = _pitch_lines(text)
    assert "NEWER" in open_lines[0]
    assert "OLDER" in open_lines[1]


def test_core_block_renders_verbatim_after_head():
    """core_block arrives pre-rendered (butler handles html/escaping) — build_digest
    must append it verbatim, before the section spacer."""
    text = build_digest([], date_label="2026-07-19", core_block="💶 CORE-BLOCK")
    head, rest = text.split("\n\n", 1)
    assert "💶 CORE-BLOCK" in head
    assert "💶 CORE-BLOCK" not in rest


def test_no_core_block_leaves_digest_unchanged():
    assert "💶" not in build_digest([], date_label="2026-07-19")


def test_no_open_pitches_line_explains_inaction():
    text = build_digest([], date_label="2026-07-19")
    assert "richtige Aktion" in text


# ===== Telegram diet (2026-08-04): condensed sections + cockpit deep links =====

AUTODEPOT = {
    "as_of": "2026-08-03", "equity": 100020.0, "equity_eur": 86878.0,
    "day_pnl": -1073.0, "day_return": -0.0106, "total_return": 0.0004,
    "benchmark_return": 0.012, "gross_exposure": 0.59, "drawdown": 0.011,
    "breaker_stage": 0, "mode": "anchor",
    "trades": [
        {"ticker": "MU", "delta_weight": -0.041},
        {"ticker": "AIRT", "delta_weight": -0.0006},
        {"ticker": "BIL", "delta_weight": -0.0006},
    ],
    "risk_events": ["Einzeltitel-Limit 10% griff bei: SPY, VEU"],
}


def test_autodepot_headline_folds_in_the_day_move():
    """One line for what the depot is worth and what it did today — not two."""
    text = build_digest([], date_label="2026-08-04", autodepot=AUTODEPOT)
    assert "🤖 Auto-Depot 100.020 $ (86.878 €) · 🔴 heute −1,1 %" in text


def test_autodepot_context_line_keeps_only_total_vs_benchmark():
    text = build_digest([], date_label="2026-08-04", autodepot=AUTODEPOT)
    assert "  Gesamt +0,0 % vs SPY +1,2 %" in text
    assert "Exposure" not in text  # dashboard: DepotsView
    assert "Drawdown" not in text
    assert "Anker-Phase" not in text


def test_autodepot_trades_summarise_immaterial_moves():
    """12 rebalances of 60 $ must not become 12 lines: name the material ones,
    count the rest."""
    text = build_digest([], date_label="2026-08-04", autodepot=AUTODEPOT)
    assert "  Trades: ↓MU 4,1 % · +2 kleine" in text


def test_autodepot_risk_events_stay_visible():
    """Risk interventions are LOUD content — they never get summarised away."""
    text = build_digest([], date_label="2026-08-04", autodepot=AUTODEPOT)
    assert "  ⚠ Einzeltitel-Limit 10% griff bei: SPY, VEU" in text


def test_autodepot_breaker_stage_still_reported():
    """A gripping breaker is the one detail that must survive the diet."""
    text = build_digest(
        [], date_label="2026-08-04", autodepot={**AUTODEPOT, "breaker_stage": 2}
    )
    assert "⛔ Drawdown-Breaker aktiv: komplett Cash" in text


def test_autodepot_stale_stand_is_flagged():
    text = build_digest(
        [], date_label="2026-08-04", autodepot={**AUTODEPOT, "stale_days": 3}
    )
    assert "⚠️ Stand 3 Handelstage alt" in text


SHORTTERM = [
    {"lane": "event", "label": "Event-Swing", "day_pnl": 0.0, "total_return": 0.005,
     "benchmark_ticker": "SPY", "benchmark_return": 0.022, "trades_today": 0,
     "promotion": {"realized_trades": 1, "days_active": 15, "profit_factor": None,
                   "eligible": False}},
    {"lane": "intraday", "label": "Intraday-Session", "day_pnl": 0.0,
     "total_return": -0.018, "stale_days": 7,
     "promotion": {"realized_trades": 10, "days_active": 15, "profit_factor": 0.22,
                   "eligible": False}},
    {"lane": "crypto", "label": "Crypto", "day_pnl": 0.0, "total_return": 0.0,
     "benchmark_ticker": "BTC-USD", "benchmark_return": -0.024,
     "promotion": {"realized_trades": 0, "days_active": 15, "profit_factor": None,
                   "eligible": False}},
]


def test_arena_renders_one_summary_line():
    text = build_digest([], date_label="2026-08-04", shortterm=SHORTTERM)
    assert "⚡ Arena 3 Lanes · beste Event-Swing +0,5 % · heute ±0 $" in text
    assert "Prüfstand" not in text  # per-lane counters live in the cockpit


def test_arena_reports_a_stale_lane_because_that_is_a_malfunction():
    text = build_digest([], date_label="2026-08-04", shortterm=SHORTTERM)
    assert "  ⚠ Intraday-Session: 7 Tage keine Daten" in text


def test_arena_announces_a_lane_that_passed_its_test_bench():
    lanes = [{**SHORTTERM[0], "promotion": {**SHORTTERM[0]["promotion"], "eligible": True}}]
    text = build_digest([], date_label="2026-08-04", shortterm=lanes)
    assert "  ✅ Event-Swing hat den Prüfstand bestanden" in text


def test_arena_marks_a_promoted_lane():
    lanes = [{**SHORTTERM[0], "promoted": True}]
    text = build_digest([], date_label="2026-08-04", shortterm=lanes)
    assert "  🎓 Event-Swing verdient jetzt Depot-Kapital" in text


def test_chances_render_one_line_without_red_verdicts():
    """A red verdict is not a chance — the line names only what the model likes."""
    opportunities = [
        {"ticker": "GOOD", "composite": 0.75, "in_zone": True,
         "breakdown": {"value": 0.9, "quality": 0.8, "momentum": 0.7, "growth": 0.6},
         "readings": [{"reason": "solide", "score": 0.6}]},
        {"ticker": "BAD", "composite": 0.30, "in_zone": True,
         "breakdown": {"value": 0.2, "quality": 0.1, "momentum": 0.1, "growth": 0.1},
         "readings": [{"reason": "schwach", "score": 0.05}]},
    ]
    text = build_digest([], date_label="2026-08-04", opportunities=opportunities)
    assert "🎯 Chancen: GOOD 75" in text
    assert "BAD" not in text


def test_chances_say_so_when_nothing_qualifies():
    opportunities = [
        {"ticker": "BAD", "composite": 0.30, "in_zone": True,
         "breakdown": {"value": 0.2, "quality": 0.1, "momentum": 0.1, "growth": 0.1},
         "readings": [{"reason": "schwach", "score": 0.05}]},
    ]
    text = build_digest([], date_label="2026-08-04", opportunities=opportunities)
    assert "🎯 Keine attraktive Chance heute — Nichtstun ist die richtige Aktion." in text


def test_open_pitches_collapse_to_a_count_and_the_new_ones():
    """Repeating yesterday's list every day is noise; only new pitches earn a line."""
    pitches = [
        {"id": 1, "ticker": "NEW", "status": "open", "composite": 0.6, "price": 10.0,
         "created_at": "2026-08-04T10:00:00+00:00", "decided_at": None,
         "verdict": "green", "verdict_why": "starke Signale"},
        {"id": 2, "ticker": "OLD", "status": "open", "composite": 0.5, "price": 20.0,
         "created_at": "2026-07-16T10:00:00+00:00", "decided_at": None,
         "verdict": "yellow", "verdict_why": "gemischt"},
    ]
    text = build_digest(
        pitches, date_label="2026-08-04", decided_since="2026-08-03T18:00:00+00:00"
    )
    assert "📬 2 Pitches offen · 1 neu" in text
    assert "  🟢 NEW · 60/100 · 10.00" in text
    assert "OLD" not in text  # unchanged since 2026-07-16 — cockpit, not phone


def test_open_pitches_without_new_ones_stay_a_single_line():
    pitches = [
        {"id": 2, "ticker": "OLD", "status": "open", "composite": 0.5, "price": 20.0,
         "created_at": "2026-07-16T10:00:00+00:00", "decided_at": None,
         "verdict": "yellow", "verdict_why": "gemischt"},
    ]
    text = build_digest(
        pitches, date_label="2026-08-04", decided_since="2026-08-03T18:00:00+00:00"
    )
    assert "📬 1 Pitch offen · nichts neu" in text
    assert "OLD" not in text


def test_earnings_collapse_to_one_line_naming_today():
    earnings = [
        {"ticker": "CAT", "earnings_date": "2026-08-04"},
        {"ticker": "SHIP", "earnings_date": "2026-08-04"},
        {"ticker": "INSW", "earnings_date": "2026-08-05"},
    ]
    text = build_digest([], date_label="2026-08-04", earnings_this_week=earnings)
    assert "📅 Earnings heute: CAT, SHIP · 1 weitere diese Woche" in text


def test_earnings_line_without_any_today():
    earnings = [{"ticker": "INSW", "earnings_date": "2026-08-05"}]
    text = build_digest([], date_label="2026-08-04", earnings_this_week=earnings)
    assert "📅 Earnings: heute keine · 1 diese Woche" in text


def test_evidence_collapses_to_one_line_while_nothing_is_resolved():
    stats = {
        "congress": {"n_resolved": 0, "n_open": 880, "hit_rate": 0.0,
                     "mean_relative_return": 0.0},
        "news_theme": {"n_resolved": 0, "n_open": 160, "hit_rate": 0.0,
                       "mean_relative_return": 0.0},
    }
    text = build_digest([], date_label="2026-08-04", evidence_stats=stats)
    assert "🔬 Evidenz: 1.040 offen, noch keine Auflösung" in text
    assert "Trefferquote" not in text


def test_evidence_line_names_the_best_measured_source_once_resolved():
    stats = {
        "congress": {"n_resolved": 12, "n_open": 880, "hit_rate": 0.58,
                     "mean_relative_return": 0.021},
        "news_theme": {"n_resolved": 4, "n_open": 160, "hit_rate": 0.25,
                       "mean_relative_return": -0.01},
    }
    text = build_digest([], date_label="2026-08-04", evidence_stats=stats)
    assert "🔬 Evidenz: 16 aufgelöst · beste Quelle Kongress-Käufe 58 %" in text


def test_below_threshold_count_no_longer_appears():
    """A daily 'N names sat under the gate' count is dashboard bookkeeping."""
    text = build_digest([], date_label="2026-08-04", below_threshold=26)
    assert "Qualitätsschwelle" not in text


def test_section_heads_link_into_the_cockpit_in_html_mode():
    text = build_digest(
        [], date_label="2026-08-04", autodepot=AUTODEPOT,
        dash_url="https://wsl-claude.tailnet.ts.net:8420", html=True,
    )
    assert (
        '<b><a href="https://wsl-claude.tailnet.ts.net:8420/?view=depots">'
        "🤖 Auto-Depot" in text
    )


def test_plain_text_mode_never_links():
    """stdout/SMTP rendering stays link-free — a bare URL is noise there."""
    text = build_digest(
        [], date_label="2026-08-04", autodepot=AUTODEPOT,
        dash_url="https://example.test", html=False,
    )
    assert "<a href" not in text
    assert "🤖 Auto-Depot" in text


def test_without_dash_url_heads_stay_plain_bold():
    text = build_digest([], date_label="2026-08-04", autodepot=AUTODEPOT, html=True)
    assert "<a href" not in text
    assert "<b>🤖 Auto-Depot" in text


def test_dash_url_is_escaped():
    text = build_digest(
        [], date_label="2026-08-04", autodepot=AUTODEPOT,
        dash_url="https://host/?a=1&b=2", html=True,
    )
    assert "&amp;b=2" in text  # a raw & would break Telegram's HTML parser


def test_dash_token_is_appended_to_the_deep_links(tmp_path):
    """Nico 2026-08-05: "am besten über Telegram den Link inkl Token immer schicken" —
    a fresh browser (or one whose es_dash cookie expired) otherwise lands on a 401.
    The token rides as a query param, which api.py's middleware exchanges for the
    httponly cookie on first load; the frontend then strips it from the visible URL."""
    text = build_digest(
        [], date_label="2026-08-05", autodepot=AUTODEPOT,
        dash_url="https://host:8420", dash_token="abc123", html=True,
    )
    # &amp; not a raw & — same reason as test_dash_url_is_escaped above.
    assert '<a href="https://host:8420/?view=depots&amp;token=abc123">' in text


def test_without_a_dash_token_the_links_stay_token_free():
    text = build_digest(
        [], date_label="2026-08-05", autodepot=AUTODEPOT,
        dash_url="https://host:8420", html=True,
    )
    assert "token=" not in text
    assert '<a href="https://host:8420/?view=depots">' in text


def test_plain_text_mode_never_leaks_the_token():
    """The stdout/SMTP rendering has no links at all, so it must not carry the secret
    either — otherwise a piped digest in copilot.log would hold it in plain text."""
    text = build_digest(
        [], date_label="2026-08-05", autodepot=AUTODEPOT,
        dash_url="https://host:8420", dash_token="abc123", html=False,
    )
    assert "abc123" not in text
