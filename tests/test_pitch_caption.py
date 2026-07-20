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
        eur_price=158.60,
        press_lines=["Analysts split on NVIDIA after earnings — Reuters"],
    )
    # v8: bold HTML head + paragraph blocks (sent with parse_mode="HTML").
    assert caption.splitlines()[0] == "<b>📈 NVDA — NVIDIA Corp.</b>"
    # v9: factor heads are words only — numeric ranks read as prices to a lay reader.
    assert "Score 81/100" in caption and "stark: Momentum, Growth" in caption
    assert "\n\n" in caption  # paragraph blocks, not a wall of lines
    assert "KGV 45" in caption and "1 Jahr +38 %" in caption
    assert "Kurs 172.40 USD (≈ 158.60 €)" in caption
    assert "Zone 165.00–170.00" in caption
    assert "Analysten-Ø-Ziel 190.00" in caption and "+10 %" in caption
    assert "🗞️ Analysts split on NVIDIA" in caption
    assert "⚠️" in caption
    # Disclaimer + delay footer removed on Nico's call (2026-07-15).
    assert "Anlagerat" not in caption and "15 Min" not in caption
    assert len(caption) <= 980


def test_caption_omits_missing_data_lines():
    caption = build_pitch_caption(_entry(readings=[]), fundamentals=None)
    assert "KGV" not in caption
    assert "1 Jahr" not in caption
    assert "Analysten" not in caption
    assert "⚠️" not in caption
    assert "🗞️" not in caption
    assert "€" not in caption  # no FX rate -> no made-up conversion
    assert "Kurs 172.40" in caption


def test_caption_hard_cap():
    caption = build_pitch_caption(_entry(name="X" * 3000), fundamentals=None)
    assert len(caption) <= 980


TARGET_STOP = {"target": 190.0, "stop": 150.0, "sigma": 0.02, "horizon_days": 40}


def test_caption_shows_target_stop_when_present():
    caption = build_pitch_caption(
        _entry(),
        Fundamentals(trailing_pe=None, analyst_target=None, analyst_count=None, currency="USD"),
        target_stop=TARGET_STOP,
    )
    assert "🎯 Kursziel 190.00 USD" in caption
    assert "🛑 Stop 150.00 USD" in caption


def test_caption_omits_target_stop_line_when_none():
    """Honest gap: the caption is compact by convention (missing optional data is simply
    omitted, e.g. KGV/Analysten/⚠️ above) — no target_stop means no line, not a placeholder."""
    caption = build_pitch_caption(_entry(), fundamentals=None, target_stop=None)
    assert "🛑" not in caption
    assert "Kursziel" not in caption


def test_caption_target_stop_label_distinct_from_entry_zone_label():
    """The pre-existing 🎯 Zone line (rule-based entry.compute_entry_plan zone) and the new
    🎯 Kursziel line (model-derived entry.compute_target_stop) share the emoji but must stay
    distinguishable by their label — never conflated into one figure."""
    caption = build_pitch_caption(_entry(), fundamentals=None, target_stop=TARGET_STOP)
    assert "🎯 Zone 165.00–170.00" in caption
    assert "🎯 Kursziel 190.00" in caption


def test_caption_stays_under_hard_cap_with_target_stop():
    caption = build_pitch_caption(
        _entry(name="X" * 900), fundamentals=None, target_stop=TARGET_STOP
    )
    assert len(caption) <= 980
