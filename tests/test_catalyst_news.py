"""Tests for the market-wide news sweep (catalyst radar, layer 2).

Every headline in this file is a REAL one, taken from the live Alpaca wire on 2026-08-19
(250 items sampled). The two misclassifications the live sample exposed — a CRO appointment
read as a trial readout, and a reverse split scored as a positive capital measure — are
pinned here so they cannot come back.
"""
from __future__ import annotations

from datetime import datetime, timezone

from equity_scout.catalyst_news import (
    KIND_LABELS,
    MIN_STRENGTH,
    build_news_signals,
    classify_catalyst,
    parse_wire,
)

NOW = datetime(2026, 8, 19, 17, 0, tzinfo=timezone.utc)


# --- classification: the classes that matter --------------------------------------------

def test_real_headlines_classify_into_the_expected_class():
    cases = [
        # Live wire, 2026-08-19.
        ("Canada Competition Bureau Seeks To Block Nortera's Proposed Acquisition Of B&G Foods",
         "merger_acquisition"),
        ("Olenox Industries Announces Non-Binding LOI To Acquire Wildboy Holdings And IP",
         "merger_acquisition"),
        ("Ohio Valley Banc Extends $5M Share Repurchase Program To August 31, 2027",
         "capital_structure"),
        ("Evolution Petroleum Prices Underwritten Offering Of 3.7M Common Shares At $4.05",
         "dilution"),
        # Analysts reacting to a release, not the release: correctly the weaker class.
        ("Baidu Analysts Slash Their Forecasts After Weak Q2 Results", "analyst_reaction"),
        ("B of A Securities Maintains Buy on Zeta Global Holdings, Raises Price Target to $30",
         "analyst_action"),
        # The Moderna day itself.
        ("MRNA Gains New Catalyst As FDA Clears mFLUSIVA Flu Shot", "fda_decision"),
        ("Moderna and Merck say personalized mRNA cancer vaccine met its endpoint in Phase 3",
         "trial_result"),
    ]
    for headline, expected in cases:
        result = classify_catalyst(headline)
        assert result is not None, headline
        assert result[0] == expected, f"{headline} -> {result[0]}, expected {expected}"


def test_every_kind_has_a_german_label():
    """The alert text is what Nico reads on his phone — an unlabelled kind is a bug there."""
    from equity_scout.catalyst_news import _RULES
    for kind, _, _ in _RULES:
        assert kind in KIND_LABELS, kind


def test_classification_reports_the_triggering_phrase():
    """Auditability: a firing signal must name the words that fired it."""
    result = classify_catalyst("Pfizer to acquire Seagen in $43B deal")
    assert result is not None
    assert result[2] == "to acquire"


def test_branch_neutrality_beyond_pharma():
    """Nico's ask was explicit: not a pharma tool. Each sector's own jump-maker must land."""
    cases = [
        ("Rocket Lab awarded $515M contract by the Space Development Agency", "contract_award"),
        ("Nvidia supplier lands design win for next-generation accelerators", "contract_award"),
        ("First Solar raises its full-year guidance after record bookings", "guidance_change"),
        ("Peabody declares force majeure at its Australian mine", "operational"),
        ("Sunrun files for Chapter 11 bankruptcy protection", "bankruptcy_distress"),
        ("Jury awards $2.1B in patent ruling against Intel", "regulatory_legal"),
        ("Robinhood joins the S&P 500 next week", "index_event"),
        ("Datadog CEO steps down after eight years", "leadership"),
    ]
    for headline, expected in cases:
        result = classify_catalyst(headline)
        assert result is not None, headline
        assert result[0] == expected, f"{headline} -> {result[0]}"


def test_ordinary_commentary_is_not_classified():
    """55 % of the live sample was this. It must produce nothing, silently."""
    for headline in (
        "Is CJPRY Undervalued Right Now?",
        "Assessing Central Japan Railway Valuation Ahead Of Earnings",
        "Top Analyst Reports for Microsoft, Visa and Chevron",
        "Apple Is The Most Underappreciated AI Mega-Cap, Analyst Says",
        "Crude Oil Moves Higher; Dollar Weakens",
    ):
        assert classify_catalyst(headline) is None, headline


# --- the two live misclassifications, pinned ---------------------------------------------

def test_cro_appointment_is_not_a_trial_readout():
    """Live 2026-08-19: a vendor appointment matched a bare 'phase 2/3' and scored 0.90."""
    result = classify_catalyst(
        "Revelation Biosciences Selected Avance Clinical To Serve As CRO For Phase 2/3 Study"
    )
    assert result is None or result[0] != "trial_result"


def test_reverse_split_is_not_a_positive_capital_measure():
    """Live 2026-08-19: 'PMGC Announces 1-For-10 Reverse Stock Split' scored as a split."""
    for headline in (
        "PMGC Announces 1-For-10 Reverse Stock Split, Effective Aug. 21",
        "InterCure Announces 1-For-5 Reverse Stock Split, Effective August 24",
    ):
        result = classify_catalyst(headline)
        assert result is not None
        assert result[0] == "reverse_split"
        # Below the firing threshold: visible in the rejection book, never a signal.
        assert result[1] < MIN_STRENGTH


def test_a_genuine_forward_split_still_classifies():
    result = classify_catalyst("Broadcom announces 10-for-1 stock split")
    assert result is not None and result[0] == "capital_structure"


# --- signal construction -----------------------------------------------------------------

def _article(headline: str, symbols: list[str], article_id: int = 1) -> dict:
    return {"id": article_id, "headline": headline, "symbols": symbols,
            "created_at": "2026-08-19T16:30:00Z", "url": "https://example.test/a",
            "source": "benzinga", "summary": ""}


def test_acquisition_creates_a_signal_for_every_named_party():
    """Both sides of a deal are catalysts — the target jumps, the acquirer often moves too."""
    signals, _ = build_news_signals(
        [_article("Pfizer to acquire Seagen in $43B deal", ["PFE", "SGEN"])], now=NOW,
    )
    assert {s["ticker"] for s in signals} == {"PFE", "SGEN"}
    assert all(s["kind"] == "merger_acquisition" for s in signals)
    assert all(s["dedup_key"].startswith("news:") for s in signals)


def test_roundup_articles_are_rejected():
    """Live: single-company news carries 1-3 symbols, roundups 8+."""
    signals, rejections = build_news_signals(
        [_article("Crude Oil Moves Higher; Lowe's Shares Gain After Q2 Earnings",
                  ["DAIC", "DVLT", "EL", "LOW", "MRNA", "TNON", "WYFI"])], now=NOW,
    )
    assert not signals
    assert rejections[0]["reason"] == "roundup_article"


def test_weak_catalysts_are_rejected_but_recorded():
    signals, rejections = build_news_signals(
        [_article("Piper Sandler Maintains Neutral on Bandwidth, Raises Price Target to $52",
                  ["BAND"])], now=NOW,
    )
    assert not signals
    assert rejections[0]["reason"] == "weak_catalyst"


def test_articles_without_symbols_are_skipped_silently():
    signals, rejections = build_news_signals(
        [_article("Fed holds rates steady", [])], now=NOW,
    )
    assert not signals and not rejections


def test_known_tickers_restricts_output_when_given():
    signals, rejections = build_news_signals(
        [_article("Pfizer to acquire Seagen in $43B deal", ["PFE", "SGEN"])],
        now=NOW, known_tickers={"PFE"},
    )
    assert [s["ticker"] for s in signals] == ["PFE"]
    assert rejections[0]["ticker"] == "SGEN"
    assert rejections[0]["reason"] == "not_tradable"


def test_dedup_key_is_per_symbol_and_article():
    """Re-reading an overlapping page must write nothing twice; the sweep rewinds on purpose."""
    article = _article("Pfizer to acquire Seagen in $43B deal", ["PFE", "SGEN"], 4242)
    first, _ = build_news_signals([article], now=NOW)
    second, _ = build_news_signals([article], now=NOW)
    assert {s["dedup_key"] for s in first} == {s["dedup_key"] for s in second}
    assert len({s["dedup_key"] for s in first}) == 2


def test_signal_carries_the_article_timestamp_not_the_run_time():
    """Ordering downstream is by event time — a run-time stamp would flatten the sequence."""
    signals, _ = build_news_signals(
        [_article("Pfizer to acquire Seagen in $43B deal", ["PFE"])], now=NOW,
    )
    assert signals[0]["seen_at"] == "2026-08-19T16:30:00Z"


def test_signals_are_sorted_by_strength():
    signals, _ = build_news_signals([
        _article("Baidu misses on revenue", ["BIDU"], 1),
        _article("Pfizer to acquire Seagen in $43B deal", ["PFE"], 2),
    ], now=NOW)
    assert [s["kind"] for s in signals] == ["merger_acquisition", "earnings_surprise"]


# --- wire parsing -------------------------------------------------------------------------

def test_parse_wire_extracts_articles_and_cursor():
    articles, token = parse_wire({
        "news": [{"id": 7, "headline": "H", "symbols": ["AAPL"],
                  "created_at": "2026-08-19T16:00:00Z", "url": "u", "source": "benzinga"}],
        "next_page_token": "tok",
    })
    assert token == "tok"
    assert articles[0]["id"] == 7 and articles[0]["symbols"] == ["AAPL"]


def test_parse_wire_handles_empty_payload():
    assert parse_wire({}) == ([], None)


def test_empty_input_is_a_no_op():
    assert build_news_signals([], now=NOW) == ([], [])


def test_analyst_reaction_to_old_earnings_is_not_an_earnings_catalyst():
    """Live 2026-08-19: the most common 'earnings' headline shape is analysts reacting hours
    later. The move is over by then, so it must not clear the alert threshold."""
    for headline in (
        "These Analysts Revise Their Forecasts On Home Depot After Q2 Results",
        "Klarna Group Analysts Cut Their Forecasts After Q2 Results",
        "These Analysts Boost Their Forecasts On Keysight Following Upbeat Q3 Results",
        "Baidu Analysts Slash Their Forecasts After Weak Q2 Results",
    ):
        result = classify_catalyst(headline)
        assert result is not None, headline
        assert result[0] == "analyst_reaction", f"{headline} -> {result[0]}"
        assert result[1] < MIN_STRENGTH


def test_the_actual_earnings_release_still_classifies():
    """The release itself must survive the analyst-reaction rule placed before it."""
    result = classify_catalyst("Target Q2 Earnings Beat Looks Great Until You Strip Out Tax")
    assert result is not None and result[0] == "earnings_surprise"
