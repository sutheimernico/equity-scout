"""v8 digest: market head (regime + sectors), the now-dropped quality-gate count, HTML
variant."""
from __future__ import annotations

from equity_scout.digest import build_digest
from equity_scout.regime import build_regime

DATE = "2026-07-16"


def _uptrend(n: int = 250) -> list[float]:
    return [100.0 + i * 0.1 for i in range(n)]


def _regime() -> dict:
    return build_regime(_uptrend(), 18.0, None, 42.0, 13.0)  # 3/3 green, breadth absent


def test_digest_head_carries_regime_and_sectors():
    text = build_digest(
        [], date_label=DATE,
        regime=_regime(),
        sector_line="Stärkste Sektoren: Energy (+12 %), Technology (+9 %)",
    )
    head = text.splitlines()[:3]
    assert head[0] == f"Copilot-Digest {DATE}"
    assert head[1] == "🟢 Marktlage: Risk-on (3/3 Signale grün)"
    assert head[2].startswith("📊 Stärkste Sektoren: Energy")


def test_digest_head_degrades_honestly_without_data():
    text = build_digest([], date_label=DATE)
    assert "Marktlage" not in text
    assert "📊" not in text


def test_below_threshold_count_is_deliberately_not_rendered():
    """2026-08-04 diet: the daily 'N Watchlist-Titel unter der Qualitätsschwelle' count
    duplicated the chances line and was dashboard bookkeeping — dropped.
    `below_threshold` stays an accepted parameter (see build_digest's signature) but
    nothing renders, regardless of the count."""
    assert "Qualitätsschwelle" not in build_digest([], date_label=DATE, below_threshold=4)
    assert "Qualitätsschwelle" not in build_digest([], date_label=DATE, below_threshold=0)


def test_digest_html_variant_bolds_heads_and_escapes():
    pitch = {"status": "open", "ticker": "T&T", "composite": 0.6, "price": 10.0,
             "created_at": "2026-07-16T10:00:00+00:00", "decided_at": None}
    text = build_digest(
        [pitch], date_label=DATE, regime=_regime(),
        sector_line="Stärkste Sektoren: Energy (+12 %)", html=True,
    )
    assert text.splitlines()[0] == f"<b>Copilot-Digest {DATE}</b>"
    # 2026-08-04 diet: "Offene Pitches: N" became the condensed "N Pitch(es) offen ·
    # <neu-suffix>" head — still a bold section head with no dynamic content to escape.
    assert "<b>📬 1 Pitch offen · 1 neu</b>" in text
    assert "T&amp;T" in text and "T&T" not in text
    # One <b> pair per line — line-based splitting can never sever a tag.
    assert all(line.count("<b>") == line.count("</b>") for line in text.splitlines())


def test_digest_plain_variant_stays_tag_free():
    text = build_digest(
        [], date_label=DATE, regime=_regime(), sector_line="Stärkste Sektoren: Energy (+12 %)",
    )
    assert "<b>" not in text
