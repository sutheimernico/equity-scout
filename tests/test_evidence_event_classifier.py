"""Deterministic beat/miss/guidance classifier (Strang B3): keyword/phrase matching
only, conservative fallback to "unknown" — never a guess."""
from __future__ import annotations

from equity_scout.evidence.base import SOURCE_8K, EvidenceEvent
from equity_scout.evidence.event_classifier import (
    EVENT_BEAT,
    EVENT_EARNINGS_FILED,
    EVENT_GUIDANCE_DOWN,
    EVENT_GUIDANCE_UP,
    EVENT_MISS,
    EVENT_OTHER_8K,
    EVENT_UNKNOWN,
    SOURCE_NEWS,
    build_classified_events,
    classify_8k_items,
    classify_headline,
)


def test_classify_headline_beat_examples():
    assert classify_headline("Acme Corp beats estimates in Q2") == EVENT_BEAT
    assert classify_headline("Acme tops Wall Street estimates for third quarter") == EVENT_BEAT
    assert classify_headline("BEATS EXPECTATIONS: Acme Q3 results impress") == EVENT_BEAT
    assert classify_headline("Acme surpasses profit forecasts on strong demand") == EVENT_BEAT


def test_classify_headline_miss_examples():
    assert classify_headline("Acme Corp misses estimates, shares fall") == EVENT_MISS
    assert classify_headline("Acme falls short of expectations in Q2") == EVENT_MISS
    assert classify_headline("Acme fell short on revenue") == EVENT_MISS


def test_classify_headline_guidance_examples():
    assert classify_headline("Acme raises full-year guidance") == EVENT_GUIDANCE_UP
    assert classify_headline("Acme lifts outlook after strong quarter") == EVENT_GUIDANCE_UP
    assert classify_headline("Acme cuts guidance amid weak demand") == EVENT_GUIDANCE_DOWN
    assert classify_headline("Acme lowers full-year outlook") == EVENT_GUIDANCE_DOWN


def test_classify_headline_unknown_for_unrelated_news():
    assert classify_headline("Acme announces new CEO") == EVENT_UNKNOWN
    assert classify_headline("Acme opens new factory in Texas") == EVENT_UNKNOWN
    assert classify_headline("") == EVENT_UNKNOWN


def test_classify_headline_negation_is_conservative_not_a_guess():
    """A negated match voids that category rather than flipping to the opposite one —
    "fails to beat" is not a beat, but it is also not confidently a miss."""
    assert classify_headline("Acme fails to beat estimates in Q2") == EVENT_UNKNOWN
    assert classify_headline("Acme failed to beat forecasts") == EVENT_UNKNOWN


def test_classify_headline_mixed_signal_is_unknown():
    """Two categories firing in one headline is a genuine dual event — never collapsed
    into a single, possibly-wrong bucket."""
    assert classify_headline("Acme beats estimates but cuts guidance") == EVENT_UNKNOWN


def test_classify_headline_wall_street_phrase_is_not_a_beat():
    """"Top Wall Street ..." is boilerplate finance-headline framing, not an earnings
    beat — the bare `street` keyword must never fire on it."""
    assert (
        classify_headline("Top Wall Street analysts raise price targets on Acme stock")
        == EVENT_UNKNOWN
    )
    assert classify_headline("Top Wall Street picks for July") == EVENT_UNKNOWN


def test_classify_headline_hedged_negation_is_unknown():
    """"will not beat" / "unlikely to beat" are negated forecasts, not beats."""
    assert (
        classify_headline("Analysts expect Acme will not beat estimates this quarter")
        == EVENT_UNKNOWN
    )
    assert (
        classify_headline("Acme is unlikely to beat estimates, analysts say")
        == EVENT_UNKNOWN
    )


def test_classify_8k_items_earnings_vs_other():
    assert classify_8k_items(["2.02"]) == EVENT_EARNINGS_FILED
    assert classify_8k_items(["2.02", "9.01"]) == EVENT_EARNINGS_FILED
    assert classify_8k_items(["7.01"]) == EVENT_OTHER_8K
    assert classify_8k_items(["8.01"]) == EVENT_OTHER_8K
    assert classify_8k_items([]) == EVENT_OTHER_8K


def test_build_classified_events_from_news_and_8k():
    news_by_ticker = {
        "aapl": [
            {"title": "Apple beats estimates", "published": "2026-07-10", "link": "http://x"},
            {"title": "Apple opens new store", "published": "", "link": "http://y"},
        ]
    }
    eightk_events = [
        EvidenceEvent(
            source=SOURCE_8K,
            ticker="msft",
            event_key="0000320193-26-000011",
            event_date="2026-07-01",
            details={
                "items": ["2.02"],
                "filing_date": "2026-07-01",
                "published_at": "2026-07-01T20:30:00.000Z",
            },
        )
    ]
    events = build_classified_events(news_by_ticker=news_by_ticker, eightk_events=eightk_events)
    assert len(events) == 3

    news_beat, news_other = events[0], events[1]
    assert news_beat.ticker == "AAPL"
    assert news_beat.event_type == EVENT_BEAT
    assert news_beat.source == SOURCE_NEWS
    assert news_beat.published_at == "2026-07-10"
    assert news_beat.detail == "Apple beats estimates"
    assert news_beat.event_key.startswith("news-AAPL-")

    # honest NULL: an empty "published" from parse_news must never be backfilled
    assert news_other.published_at is None

    eightk = events[2]
    assert eightk.ticker == "MSFT"
    assert eightk.event_type == EVENT_EARNINGS_FILED
    assert eightk.source == SOURCE_8K
    assert eightk.published_at == "2026-07-01T20:30:00.000Z"
    assert eightk.event_key == "edgar_8k-0000320193-26-000011"


def test_build_classified_events_8k_missing_published_at_is_null():
    eightk_events = [
        EvidenceEvent(
            source=SOURCE_8K,
            ticker="MSFT",
            event_key="acc-1",
            event_date="2026-07-01",
            details={"items": ["7.01"], "filing_date": "2026-07-01"},
        )
    ]
    events = build_classified_events(news_by_ticker={}, eightk_events=eightk_events)
    assert events[0].published_at is None
    assert events[0].event_type == EVENT_OTHER_8K


def test_build_classified_events_skips_untitled_headlines():
    news_by_ticker = {"AAA": [{"title": "", "published": "2026-07-10"}]}
    events = build_classified_events(news_by_ticker=news_by_ticker, eightk_events=[])
    assert events == []
