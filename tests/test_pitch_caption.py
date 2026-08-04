"""Four-line photo caption (2026-08-04 Telegram diet): name + verdict, score, price +
zone, risk — nothing else, because five to ten of these arrive in a row on pitch days.
The depth the caption gave up is guarded on the Details path (build_pitch) below."""
from equity_scout.fundamentals import Fundamentals
from equity_scout.pitch import build_pitch, build_pitch_caption


def _entry(**overrides) -> dict:
    entry = {
        # "bucket" is unused by the caption but required by build_pitch's LLM fact block,
        # which the Details-path tests below exercise.
        "ticker": "NVDA", "name": "NVIDIA Corp.", "composite": 0.81, "bucket": "growth",
        "breakdown": {"value": 0.30, "quality": 0.65, "momentum": 0.92, "growth": 0.88,
                      "low_vol": 0.20},
        "price": 172.40, "entry_zone_low": 165.0, "entry_zone_high": 170.0,
        "zone_note": "Kurs über Zone", "readings": [
            {"score": 0.2, "reason": "Momentum unter 20-Tage-Schnitt"},
        ],
    }
    entry.update(overrides)
    return entry


def _full_caption():
    return build_pitch_caption(
        _entry(),
        Fundamentals(trailing_pe=45.0, analyst_target=190.0, analyst_count=30,
                     currency="USD"),
        one_year_return=0.38,
        eur_price=158.60,
        press_lines=["Analysts split on NVIDIA after earnings — Reuters"],
        target_stop=TARGET_STOP,
        f_score={"score": 7, "evaluable": 9, "fiscal_year": 2025},
    )


def test_caption_is_exactly_four_lines():
    lines = _full_caption().splitlines()
    assert len(lines) == 4


def test_caption_carries_name_verdict_price_zone_and_risk():
    lines = _full_caption().splitlines()
    # v8: bold HTML head (sent with parse_mode="HTML").
    assert lines[0] == "<b>📈 NVDA — NVIDIA Corp.</b>"
    # v9: factor heads are words only — numeric ranks read as prices to a lay reader.
    assert lines[1].startswith("🟢 <b>Einstieg attraktiv</b> · 81/100")
    assert "stark: Momentum, Growth" in lines[1]
    assert lines[2] == (
        "💰 Kurs 172.40 USD (≈ 158.60 €) · 🎯 Zone 165.00–170.00 USD"
    )
    assert lines[3].startswith("⚠️ ")
    # Disclaimer + delay footer removed on Nico's call (2026-07-15).
    assert "Anlagerat" not in _full_caption() and "15 Min" not in _full_caption()
    assert len(_full_caption()) <= 980


def test_caption_drops_the_depth_the_details_button_serves():
    """2026-08-04: KGV, 1-year return, analyst consensus, model target/stop, F-score,
    evidence and press moved OFF the caption. They are not lost — see the two
    build_pitch tests below, which is what the "🔎 Details" button replies with."""
    caption = _full_caption()
    assert "KGV" not in caption
    assert "1 Jahr" not in caption
    assert "Analysten" not in caption
    assert "Kursziel" not in caption and "🛑" not in caption
    assert "Bilanz-Trend" not in caption
    assert "🗞️" not in caption and "👥" not in caption


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


def test_details_path_shows_target_stop_when_present():
    """Moved off the caption on 2026-08-04 — but the model target/stop must still reach
    Nico somewhere, and that somewhere is the Details reply."""
    text = build_pitch(
        _entry(),
        Fundamentals(trailing_pe=None, analyst_target=None, analyst_count=None, currency="USD"),
        ask=lambda question, context: "Kurz.",
        target_stop=TARGET_STOP,
        html=True,
    )
    assert "🎯 Kursziel 190.00 USD" in text
    assert "🛑 Stop 150.00 USD" in text


def test_details_path_target_stop_label_distinct_from_entry_zone_label():
    """The 🎯 Zone line (rule-based entry.compute_entry_plan zone) and the 🎯 Kursziel line
    (model-derived entry.compute_target_stop) share the emoji but must stay distinguishable
    by their label — never conflated into one figure. Guarded on the Details path since the
    caption stopped carrying either figure's detail form."""
    text = build_pitch(
        _entry(), fundamentals=None, ask=lambda question, context: "Kurz.",
        target_stop=TARGET_STOP, html=True,
    )
    assert "Kurs über Zone" in text  # the entry zone's own wording (zone_note)
    assert "🎯 Kursziel 190.00" in text


def test_caption_stays_under_hard_cap_with_every_optional_argument():
    caption = build_pitch_caption(
        _entry(name="X" * 900), fundamentals=None, target_stop=TARGET_STOP,
        press_lines=["headline"] * 20, one_year_return=0.5, eur_price=100.0,
    )
    assert len(caption) <= 980
