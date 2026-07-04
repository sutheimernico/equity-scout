"""Pitch builder tests. LLM seam injected; fallback must be deterministic."""
from __future__ import annotations

from equity_scout.chat import ChatError
from equity_scout.pitch import PITCH_LLM_UNAVAILABLE_PREFIX, build_pitch

ENTRY = {
    "ticker": "EXE",
    "name": "Example Corp",
    "bucket": "defensive",
    "price": 90.72,
    "entry_zone_low": 84.77,
    "entry_zone_high": 103.01,
    "in_zone": True,
    "proximity": -0.119,
    "composite": 0.592,
    "zone_note": "Kurs in der Entry-Zone (84.77–103.01).",
    "breakdown": {"value": 0.8, "quality": 0.9, "momentum": 0.4, "growth": 0.5},
    "readings": [
        {"name": "dip_quality", "score": 0.75, "reason": "Kurs -22.1 % vom 52-Wochen-Hoch..."},
        {"name": "value_gap", "score": 0.72, "reason": "Kurs -8.3 % unter dem 200-Tage-Schnitt..."},
        {"name": "momentum", "score": 0.16, "reason": "Kurs unter dem 20-Tage-Schnitt..."},
    ],
}


def test_build_pitch_uses_llm_text_and_appends_facts():
    pitch = build_pitch(ENTRY, ask=lambda question, context: "Kurzer LLM-Text.")
    assert pitch.startswith("📈 EXE — Example Corp")
    assert "Kurzer LLM-Text." in pitch
    assert "Score 59/100" in pitch
    assert "84.77" in pitch and "103.01" in pitch
    assert "Keine Anlageberatung" in pitch


def test_build_pitch_falls_back_deterministically_on_chat_error():
    def broken(question, context):
        raise ChatError("ollama down")

    pitch = build_pitch(ENTRY, ask=broken)
    assert PITCH_LLM_UNAVAILABLE_PREFIX in pitch
    assert "52-Wochen-Hoch" in pitch  # readings' reasons carry the pitch instead
    assert "Score 59/100" in pitch


def test_build_pitch_stays_under_telegram_limit():
    entry = dict(ENTRY)
    entry["readings"] = [
        {"name": "dip_quality", "score": 0.7, "reason": "R" * 3000},
        {"name": "value_gap", "score": 0.7, "reason": "V" * 3000},
        {"name": "momentum", "score": 0.7, "reason": "M" * 3000},
    ]
    pitch = build_pitch(entry, ask=lambda q, c: "X" * 5000)
    assert len(pitch) <= 4000  # Telegram hard limit is 4096; headroom for edits
