"""News-theme radar: feed parsing, deterministic theme detection, ticker matching."""
from __future__ import annotations

from equity_scout.evidence.base import STATUS_FETCH_FAILED, STATUS_OK
from equity_scout.evidence.news_themes import (
    FEEDS,
    Headline,
    collect_news_themes,
    dedupe_headlines,
    detect_themes,
    match_ticker_headlines,
    parse_feed,
)

NOW = "2026-07-07T12:00:00+00:00"

RSS = """<rss version="2.0"><channel>
  <item><title>Energy prices surge across Europe</title><pubDate>x</pubDate></item>
  <item><title></title></item>
  <item><title>Second headline</title></item>
</channel></rss>"""

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Fed statement on rates</title><updated>x</updated></entry>
</feed>"""


def test_parse_feed_handles_rss_and_atom_and_skips_empty_titles():
    assert [h.title for h in parse_feed(RSS, "mw")] == [
        "Energy prices surge across Europe", "Second headline",
    ]
    assert [h.title for h in parse_feed(ATOM, "fed")] == ["Fed statement on rates"]


def _energy_headlines() -> list[Headline]:
    return [
        Headline("Energy prices surge across Europe", "google-news"),
        Headline("Rising energy prices hit manufacturers", "marketwatch"),
        Headline("What high energy prices mean for utilities", "google-news"),
        Headline("Unrelated culture piece", "google-news"),
    ]


def test_detect_themes_requires_hits_and_distinct_sources():
    themes = detect_themes(_energy_headlines())
    assert [t.keyword for t in themes] == ["energy prices"]
    assert themes[0].hits == 3
    assert themes[0].sources == ["google-news", "marketwatch"]

    # Same three hits from ONE feed only: no cross-source confirmation, no theme.
    single_source = [Headline(h.title, "google-news") for h in _energy_headlines()]
    assert detect_themes(single_source) == []


def test_dedupe_headlines_collapses_same_story_across_feeds():
    first = Headline("Energy prices surge across Europe", "google-news")
    syndicated = Headline("Energy Prices Surge Across Europe - Reuters", "fed")
    assert dedupe_headlines([first, syndicated]) == [first]


def test_detect_themes_dedupes_syndicated_story_across_a_third_feed():
    # "Energy prices surge across Europe" is the SAME wire story reprinted under a
    # different outlet suffix by a third feed. Before dedup that would be 3 hits / 3
    # sources (clears MIN_HITS=3 and MIN_SOURCES=2); after dedup the duplicate
    # collapses into its first occurrence, leaving only 2 distinct articles — below
    # MIN_HITS, so the syndicated copy must not manufacture a theme on its own.
    headlines = _energy_headlines()[:2] + [
        Headline("Energy prices surge across Europe - Reuters", "fed"),
    ]
    assert detect_themes(headlines) == []


def test_detect_themes_holds_unigrams_to_a_higher_bar():
    # "tariffs" appears 3x across two sources — enough for a bigram, NOT for a unigram.
    headlines = [
        Headline("Tariffs loom", "google-news"),
        Headline("Fresh tariffs announced", "marketwatch"),
        Headline("Tariffs debated again", "google-news"),
    ]
    assert detect_themes(headlines) == []
    doubled = headlines + [
        Headline("Tariffs escalate", "marketwatch"),
        Headline("Tariffs bite exporters", "google-news"),
        Headline("Sixth tariffs mention", "marketwatch"),
    ]
    assert [t.keyword for t in detect_themes(doubled)] == ["tariffs"]


def test_match_ticker_headlines_needs_the_phrase_in_own_news():
    themes = detect_themes(_energy_headlines())
    events = match_ticker_headlines(
        themes,
        {
            "SHEL": ["Shell gains as energy prices climb further"],
            "AAPL": ["New iPhone rumors"],
        },
        now=NOW,
    )
    assert [(e.ticker, e.details["theme"]) for e in events] == [("SHEL", "energy prices")]
    assert events[0].event_key == "energy-prices-2026w28"  # weekly rotation, not daily


def test_collect_degrades_when_all_feeds_fail_but_not_on_partial_failure():
    def all_broken(url: str) -> str:
        raise OSError("down")

    result = collect_news_themes(now=NOW, ticker_headlines={}, http_get=all_broken)
    assert result.status == STATUS_FETCH_FAILED

    feed_urls = dict(FEEDS)

    def partially_broken(url: str) -> str:
        if url == feed_urls["google-news"]:
            raise OSError("google changed something")
        return RSS

    result = collect_news_themes(now=NOW, ticker_headlines={}, http_get=partially_broken)
    assert result.status == STATUS_OK
    assert "google-news: failed" in result.detail
    assert "marketwatch: ok" in result.detail
