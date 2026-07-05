"""Pitch builder tests. LLM seam injected; fallback deterministic. The plain-language
layout carries a score band, a tranche scale-in plan, KGV, and a THIRD-PARTY analyst
consensus line with an honest-absence fallback (never a fabricated target)."""
from __future__ import annotations

from equity_scout.chat import ChatError
from equity_scout.fundamentals import Fundamentals
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
    "tranches": [
        {"label": "Jetzt", "fraction": 1 / 3, "trigger_price": 90.72},
        {"label": "bei −7 %", "fraction": 1 / 3, "trigger_price": 84.37},
        {"label": "bei −15 %", "fraction": 1 / 3, "trigger_price": 77.11},
    ],
}

FUND = Fundamentals(trailing_pe=18.4, analyst_target=120.0, analyst_count=8, currency="USD")


def _fixed(text: str = "Was: Beispielfirma. Warum: im Kennzahlen-Kontext günstig."):
    return lambda question, context: text


def test_build_pitch_plain_layout_header_score_band_tranches_disclaimer():
    pitch = build_pitch(ENTRY, ask=_fixed())
    assert pitch.startswith("📈 EXE — Example Corp")
    # 0.592 -> 59 -> "mittel" (< 70). Framed as no price promise.
    assert "Einstiegs-Score: 59/100 (mittel)" in pitch
    assert "kein Kursversprechen" in pitch
    assert "So könntest du einsteigen — in 3 Schritten:" in pitch
    assert "• Jetzt: bei ~90.72" in pitch
    assert "• bei −7 %: bei ~84.37" in pitch
    assert "in Schritten kaufen glättet den Einstiegspreis" in pitch
    assert pitch.endswith("Keine Anlageberatung.")


def test_build_pitch_renders_kgv_when_present_and_omits_when_none():
    with_pe = build_pitch(ENTRY, FUND, ask=_fixed())
    assert "KGV 18" in with_pe
    assert "günstiger bewertet" in with_pe
    no_pe = build_pitch(ENTRY, Fundamentals(None, 120.0, 8, "USD"), ask=_fixed())
    assert "KGV" not in no_pe  # honest absence: the line is dropped, not shown as "—"


def test_build_pitch_analyst_line_labels_third_party_with_signed_upside():
    pitch = build_pitch(ENTRY, FUND, ask=_fixed())
    # target 120 vs price 90.72 -> +32 %; labelled as THIRD-PARTY consensus.
    assert "Analystensicht: Ø-Kursziel 120.00 USD (8 Schätzungen) → +32 % zum aktuellen Kurs." in (
        pitch
    )
    assert "Fremde Analystenmeinungen, oft falsch" in pitch
    # currency suffix also rides the tranche reference prices
    assert "• Jetzt: bei ~90.72 USD" in pitch


def test_build_pitch_analyst_honest_absence_when_missing():
    pitch = build_pitch(ENTRY, Fundamentals(18.4, None, None, "USD"), ask=_fixed())
    assert "Analystensicht: keine Schätzung verfügbar (bei kleineren/nicht-US-Werten normal)." in (
        pitch
    )
    assert "Ø-Kursziel" not in pitch


def test_build_pitch_never_fabricates_a_target_without_fundamentals():
    """Honesty invariant 1: with no fundamentals the pitch states the honest absence
    and MUST NOT invent a target number or an implied-upside arrow."""
    pitch = build_pitch(ENTRY, None, ask=_fixed())
    assert "keine Schätzung verfügbar" in pitch
    assert "Ø-Kursziel" not in pitch
    assert "Schätzungen)" not in pitch  # no "(N Schätzungen)" marker
    assert "% zum aktuellen Kurs" not in pitch  # no fabricated implied upside


def test_build_pitch_score_band_thresholds():
    def band(composite: float) -> str:
        pitch = build_pitch({**ENTRY, "composite": composite}, ask=_fixed())
        line = next(ln for ln in pitch.splitlines() if ln.startswith("Einstiegs-Score:"))
        return line

    assert "39/100 (niedrig)" in band(0.39)
    assert "40/100 (mittel)" in band(0.40)
    assert "70/100 (hoch)" in band(0.70)


def test_build_pitch_falls_back_deterministically_but_keeps_sections():
    def broken(question, context):
        raise ChatError("ollama down")

    pitch = build_pitch(ENTRY, FUND, ask=broken)
    assert PITCH_LLM_UNAVAILABLE_PREFIX in pitch
    # structured sections survive an LLM outage — they are deterministic
    assert "Einstiegs-Score: 59/100 (mittel)" in pitch
    assert "So könntest du einsteigen" in pitch
    assert "KGV 18" in pitch
    assert "Analystensicht: Ø-Kursziel 120.00 USD" in pitch
    assert pitch.endswith("Keine Anlageberatung.")


def test_build_pitch_llm_prompt_keeps_no_forecast_guardrail():
    questions: list[str] = []

    def record(question, context):
        questions.append(question)
        return "LLM-Text."

    build_pitch(ENTRY, FUND, ask=record)
    assert "Keine Prognosen, keine Kursziele" in questions[0]


def test_build_pitch_risk_line_uses_weakest_reading():
    pitch = build_pitch(ENTRY, FUND, ask=_fixed())
    # momentum (0.16) is the lowest-scoring reading -> it is the named risk
    assert "Risiko: Kurs unter dem 20-Tage-Schnitt..." in pitch


def test_build_pitch_stays_under_telegram_limit_and_keeps_frame():
    entry = {**ENTRY, "readings": [
        {"name": "momentum", "score": 0.1, "reason": "M" * 3000},
        {"name": "value_gap", "score": 0.7, "reason": "V" * 10},
    ]}
    pitch = build_pitch(entry, FUND, ask=lambda q, c: "X" * 5000)
    assert len(pitch) <= 4000  # Telegram hard limit 4096; headroom for edit suffix
    # truncation cuts the LLM prose, never the frame: header + disclaimer survive
    assert pitch.startswith("📈 EXE — Example Corp")
    assert pitch.endswith("Keine Anlageberatung.")
    # the deterministic structured sections are never the part cut
    assert "Einstiegs-Score: 59/100 (mittel)" in pitch
    assert "Analystensicht:" in pitch
