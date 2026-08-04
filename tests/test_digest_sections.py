"""Daily digest: the "Heute aufgefallen" alert section (dropped 2026-08-04), the
condensed "🎯 Chancen" chances line, the condensed earnings line, and section order."""
from equity_scout.digest import build_digest


def test_alerts_section_is_deliberately_not_rendered():
    """The "📌 Heute aufgefallen" section was dropped in the 2026-08-04 Telegram diet —
    the dashboard's VoicesPanel (evidence.storage.load_alerts via /api/evidence) shows
    today's alerts instead. `alerts_today` stays an accepted parameter (see
    build_digest's signature) but nothing renders, even when it carries data."""
    text = build_digest(
        [], date_label="2026-07-14",
        alerts_today=[{"ticker": "KHC", "reasons": ["congress", "insider"], "buyer_count": 3}],
    )
    assert "Heute aufgefallen" not in text
    assert "KHC" not in text


def test_alerts_section_omitted_when_empty():
    text = build_digest([], date_label="2026-07-14", alerts_today=[])
    assert "Heute aufgefallen" not in text


def test_opportunities_section_renders_as_one_line_of_chances():
    """2026-08-04 diet: the old per-line "in Zone"/"unterbewertet" marks and the
    "— <verdict label>" suffix are gone — chances condense to one "🎯 Chancen: ..." line
    naming only non-red verdicts, ticker + score."""
    entries = [
        {"ticker": "NVDA", "composite": 0.81, "in_zone": True, "value_gap": 0.4,
         "breakdown": {"value": 0.7, "quality": 0.8, "momentum": 0.9, "growth": 0.6},
         "readings": [{"reason": "stark", "score": 0.7}]},
        {"ticker": "KO", "composite": 0.61, "in_zone": False, "value_gap": 0.0,
         "breakdown": {"value": 0.5, "quality": 0.6, "momentum": 0.5, "growth": 0.4},
         "readings": [{"reason": "gemischt", "score": 0.5}]},
    ]
    text = build_digest([], date_label="2026-07-14", opportunities=entries)
    assert "🎯 Chancen: NVDA 81 · KO 61" in text
    assert "in Zone" not in text
    assert "unterbewertet" not in text


def test_opportunities_line_omitted_when_empty():
    """No watchlist at all -> no chances line whatsoever. Distinct from a watchlist whose
    entries are all red, which DOES render the honest "keine attraktive Chance" line —
    pinning the current 🎯 marker instead of the retired "Chancen im Blick" heading."""
    text = build_digest([], date_label="2026-07-14", opportunities=[])
    assert "🎯" not in text


def test_section_order_header_opportunities_pitches():
    """Alerts dropped 2026-08-04 — chances now leads straight into open pitches."""
    text = build_digest(
        [{"status": "open", "ticker": "AAPL", "composite": 0.7, "price": 100.0,
          "created_at": "2026-07-14T10:00:00+00:00"}],
        date_label="2026-07-14",
        opportunities=[{
            "ticker": "NVDA", "composite": 0.8, "in_zone": False, "value_gap": 0.0,
            "breakdown": {"value": 0.7, "quality": 0.7, "momentum": 0.7, "growth": 0.7},
            "readings": [],
        }],
    )
    order = [text.index("🎯 Chancen"), text.index("📬")]
    assert order == sorted(order)


def test_earnings_section_names_only_todays_ticker_not_the_date():
    """2026-08-04 diet: a ticker NOT due on date_label is no longer named at all — only
    tickers due exactly today get named; anything later in the week is a bare count.
    AAPL's earnings_date never appears verbatim."""
    text = build_digest(
        [], date_label="2026-07-15",
        earnings_this_week=[{"ticker": "AAPL", "earnings_date": "2026-07-22"}],
    )
    assert "📅 Earnings: heute keine · 1 diese Woche" in text
    assert "AAPL" not in text
    assert "2026-07-22" not in text


def test_earnings_section_renders_multiple_tickers_due_today():
    text = build_digest(
        [], date_label="2026-07-16",
        earnings_this_week=[
            {"ticker": "AAPL", "earnings_date": "2026-07-16"},
            {"ticker": "MSFT", "earnings_date": "2026-07-16"},
        ],
    )
    assert "📅 Earnings heute: AAPL, MSFT · 0 weitere diese Woche" in text


def test_earnings_line_omitted_when_empty():
    """Pins the current 📅 marker, not the retired "Earnings diese Woche" heading."""
    text = build_digest([], date_label="2026-07-14", earnings_this_week=[])
    assert "📅" not in text


def test_earnings_line_omitted_when_none():
    text = build_digest([], date_label="2026-07-14", earnings_this_week=None)
    assert "📅" not in text


def test_section_order_header_opportunities_earnings_pitches():
    """Alerts dropped 2026-08-04 — order is now chances, earnings, pitches."""
    text = build_digest(
        [{"status": "open", "ticker": "AAPL", "composite": 0.7, "price": 100.0,
          "created_at": "2026-07-14T10:00:00+00:00"}],
        date_label="2026-07-14",
        opportunities=[{
            "ticker": "NVDA", "composite": 0.8, "in_zone": False, "value_gap": 0.0,
            "breakdown": {"value": 0.7, "quality": 0.7, "momentum": 0.7, "growth": 0.7},
            "readings": [],
        }],
        earnings_this_week=[{"ticker": "MSFT", "earnings_date": "2026-07-16"}],
    )
    order = [text.index("🎯 Chancen"), text.index("📅 Earnings"), text.index("📬")]
    assert order == sorted(order)
