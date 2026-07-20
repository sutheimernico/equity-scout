"""v8 HTML pitch layout: escaping, paragraph blocks, expandable detail quote, caps."""
from __future__ import annotations

from equity_scout.constants import SHORT_DISCLAIMER
from equity_scout.pitch import build_pitch, build_pitch_caption


def _entry(**overrides) -> dict:
    entry = {
        "ticker": "BN", "name": "Barnes & Noble <Education>", "composite": 0.81,
        "breakdown": {"value": 0.30, "quality": 0.65, "momentum": 0.92, "growth": 0.88,
                      "low_vol": 0.20},
        "price": 90.72, "entry_zone_low": 84.77, "entry_zone_high": 103.01,
        "bucket": "balanced", "zone_note": "Kurs in der Entry-Zone (84.77–103.01).",
        "readings": [{"name": "dip", "score": 0.5, "reason": "Kurs < 20-Tage-Schnitt"}],
        "tranches": [{"label": "Jetzt", "trigger_price": 90.72}],
        "in_zone": True,
    }
    entry.update(overrides)
    return entry


def _fake_ask(question: str, context: str) -> str:
    return "Zwei Sätze Einordnung."


def test_caption_escapes_dynamic_content():
    caption = build_pitch_caption(_entry())
    assert "Barnes &amp; Noble &lt;Education&gt;" in caption
    assert "<Education>" not in caption
    # The risk reason (dynamic) is escaped too.
    assert "Kurs &lt; 20-Tage-Schnitt" in caption


def test_caption_overflow_degrades_to_plain_without_tag_fragments():
    caption = build_pitch_caption(_entry(name="X" * 3000))
    assert len(caption) <= 980
    assert "<b" not in caption and "</b>" not in caption


def test_html_pitch_folds_details_into_expandable_quote():
    pitch = build_pitch(_entry(), ask=_fake_ask, html=True)
    assert pitch.startswith("<b>📈 BN — Barnes &amp; Noble &lt;Education&gt;</b>")
    assert "🟢 <b>Einstieg attraktiv</b>" in pitch
    assert pitch.count("<blockquote expandable>") == 1
    assert pitch.count("</blockquote>") == 1
    detail = pitch.split("<blockquote expandable>")[1].split("</blockquote>")[0]
    assert "So könntest du einsteigen" in detail
    assert "Kennzahlen:" in detail
    assert "Analystensicht" in detail
    # Risk + disclaimer stay OUTSIDE the fold — always visible.
    after = pitch.split("</blockquote>")[1]
    assert "⚠️" in after
    assert SHORT_DISCLAIMER in after


def test_html_pitch_survives_llm_outage():
    def broken_ask(question: str, context: str) -> str:
        from equity_scout.chat import ChatError

        raise ChatError("ollama down")

    pitch = build_pitch(_entry(), ask=broken_ask, html=True)
    assert "<blockquote expandable>" in pitch
    assert "nicht verfügbar" in pitch


def test_html_pitch_respects_limit_via_detail_cut():
    entry = _entry(readings=[
        {"name": f"r{i}", "score": 0.5, "reason": "Grund " + "x" * 200} for i in range(30)
    ])
    entry["tranches"] = [
        {"label": "Tranche " + "y" * 300, "trigger_price": 1.0} for _ in range(12)
    ]
    pitch = build_pitch(entry, ask=_fake_ask, html=True)
    assert len(pitch) <= 4000
    assert pitch.endswith(SHORT_DISCLAIMER)


def test_plain_pitch_contains_no_html():
    pitch = build_pitch(_entry(), ask=_fake_ask)
    assert "<b>" not in pitch and "<blockquote" not in pitch
    assert "Barnes & Noble" in pitch  # unescaped in the plain dashboard variant


def test_long_pitch_html_announces_expandable_details():
    pitch = build_pitch(_entry(), ask=_fake_ask, html=True)
    assert "Antippen für die ausführliche Erklärung" in pitch
