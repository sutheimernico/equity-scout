"""Compact sectioned photo caption (2026-07-15 redesign): one fact per line, hard cap."""
from equity_scout.fundamentals import Fundamentals
from equity_scout.pitch import build_pitch_caption


def _entry(**overrides) -> dict:
    entry = {
        "ticker": "NVDA", "name": "NVIDIA Corp.", "composite": 0.81,
        "breakdown": {"value": 0.30, "quality": 0.65, "momentum": 0.92, "growth": 0.88,
                      "low_vol": 0.20},
        "price": 172.40, "entry_zone_low": 165.0, "entry_zone_high": 170.0,
        "zone_note": "Kurs über Zone", "readings": [
            {"score": 0.2, "reason": "Momentum unter 20-Tage-Schnitt"},
        ],
    }
    entry.update(overrides)
    return entry


def test_caption_has_sections_and_stays_compact():
    caption = build_pitch_caption(
        _entry(),
        Fundamentals(trailing_pe=45.0, analyst_target=190.0, analyst_count=30,
                     currency="USD"),
        one_year_return=0.38,
    )
    assert caption.splitlines()[0] == "📈 NVDA — NVIDIA Corp."
    assert "Score 81/100" in caption and "Momentum 92" in caption
    assert "KGV 45" in caption and "1 Jahr +38 %" in caption
    assert "Zone 165.00–170.00" in caption
    assert "Analysten-Ø-Ziel 190.00" in caption and "+10 %" in caption
    assert "⚠️" in caption and "Kein Anlagerat" in caption
    assert len(caption) <= 980


def test_caption_omits_missing_data_lines():
    caption = build_pitch_caption(_entry(readings=[]), fundamentals=None)
    assert "KGV" not in caption
    assert "1 Jahr" not in caption
    assert "Analysten" not in caption
    assert "⚠️" not in caption
    assert "Kurs 172.40" in caption


def test_caption_hard_cap():
    caption = build_pitch_caption(_entry(name="X" * 3000), fundamentals=None)
    assert len(caption) <= 980
