"""Daily digest: 'Heute aufgefallen' (today's evidence alerts) + 'Chancen im Blick'
(top watchlist candidates) sections."""
from equity_scout.digest import build_digest


def test_alerts_section_renders_ticker_and_reasons():
    text = build_digest(
        [], date_label="2026-07-14",
        alerts_today=[{"ticker": "KHC", "reasons": ["congress", "insider"], "buyer_count": 3}],
    )
    assert "Heute aufgefallen" in text
    assert "KHC" in text
    assert "Kongress-Käufe" in text
    assert "Insider-Käufe (Form 4)" in text
    assert "3 Käufer" in text


def test_alert_reason_headlines_are_truncated():
    text = build_digest(
        [], date_label="2026-07-15",
        alerts_today=[{"ticker": "AMZN", "reasons": ["Stimme: " + "x" * 300],
                       "buyer_count": 1}],
    )
    line = next(ln for ln in text.splitlines() if "AMZN" in ln)
    assert len(line) < 110 and line.rstrip().endswith("…")


def test_alerts_section_omitted_when_empty():
    text = build_digest([], date_label="2026-07-14", alerts_today=[])
    assert "Heute aufgefallen" not in text


def test_opportunities_section_renders_marks():
    entries = [
        {"ticker": "NVDA", "composite": 0.81, "in_zone": True, "value_gap": 0.4},
        {"ticker": "KO", "composite": 0.61, "in_zone": False, "value_gap": 0.0},
    ]
    text = build_digest([], date_label="2026-07-14", opportunities=entries)
    assert "Chancen im Blick" in text
    nvda_line = next(ln for ln in text.splitlines() if "NVDA" in ln)
    assert "81/100" in nvda_line and "in Zone" in nvda_line and "unterbewertet" in nvda_line
    ko_line = next(ln for ln in text.splitlines() if "KO" in ln)
    assert "in Zone" not in ko_line and "unterbewertet" not in ko_line


def test_opportunities_section_omitted_when_empty():
    text = build_digest([], date_label="2026-07-14", opportunities=[])
    assert "Chancen im Blick" not in text


def test_section_order_header_alerts_opportunities_pitches():
    text = build_digest(
        [{"status": "open", "ticker": "AAPL", "composite": 0.7, "price": 100.0,
          "created_at": "2026-07-14T10:00:00+00:00"}],
        date_label="2026-07-14",
        alerts_today=[{"ticker": "KHC", "reasons": ["congress"], "buyer_count": 1}],
        opportunities=[{"ticker": "NVDA", "composite": 0.8, "in_zone": False, "value_gap": 0.0}],
    )
    order = [text.index("Heute aufgefallen"), text.index("Chancen im Blick"),
             text.index("Offene Pitches")]
    assert order == sorted(order)
