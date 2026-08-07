"""Voices collector: deterministic call/context boundary, feeds faked, no network."""
from __future__ import annotations

from equity_scout.evidence.base import (
    SOURCE_VOICE,
    STATUS_FETCH_FAILED,
    STATUS_OK,
    EvidenceEvent,
)
from equity_scout.evidence.person_track import calls_from_events
from equity_scout.evidence.voices import (
    KIND_CALL,
    KIND_CALL_BEARISH,
    KIND_CONTEXT,
    Mention,
    classify_mention,
    collect_voices,
    dedupe_mentions,
    parse_feed_dated,
    resolve_ticker,
)

UNIVERSE = [
    ("AAPL", "Apple Inc."),
    ("TSLA", "Tesla, Inc."),
    ("TGT", "Target Corporation"),
    ("KHC", "Kraft Heinz Co"),
]

RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>feed</title>
{items}
</channel></rss>"""


def rss(items: list[tuple[str, str]]) -> str:
    body = "\n".join(
        f"<item><title>{title}</title><pubDate>{pub}</pubDate>"
        f"<link>https://example.com</link></item>"
        for title, pub in items
    )
    return RSS_TEMPLATE.format(items=body)


def mention(title: str, speaker: str = "Michael Burry") -> Mention:
    return Mention(speaker=speaker, title=title, feed="google-news", published="2026-07-12")


# --- parsing -------------------------------------------------------------------


def test_parse_feed_dated_extracts_title_and_iso_date():
    xml = rss([("Michael Burry buys AAPL", "Sat, 12 Jul 2026 09:30:00 GMT")])
    assert parse_feed_dated(xml) == [("Michael Burry buys AAPL", "2026-07-12")]


def test_parse_feed_dated_keeps_item_with_unparseable_date_as_blank():
    xml = rss([("Michael Burry buys AAPL", "not a date")])
    assert parse_feed_dated(xml) == [("Michael Burry buys AAPL", "")]


def test_dedupe_mentions_collapses_same_story_across_feeds():
    first = mention("Michael Burry buys Apple stock")
    syndicated = Mention(
        speaker="Michael Burry",
        title="Michael Burry Buys Apple Stock!",
        feed="bing-news",
        published="2026-07-12",
    )
    assert dedupe_mentions([first, syndicated]) == [first]


# --- classification boundary ---------------------------------------------------


def test_bullish_verb_after_name_with_unique_ticker_is_a_call():
    result = classify_mention(mention("Michael Burry buys Apple shares"), UNIVERSE, [])
    assert result == (KIND_CALL, "AAPL", "bullish")


def test_bearish_verb_maps_to_bearish_call():
    result = classify_mention(mention("Michael Burry bets against TSLA"), UNIVERSE, [])
    assert result == (KIND_CALL_BEARISH, "TSLA", "bearish")


def test_ticker_without_direction_verb_is_context():
    result = classify_mention(
        mention("What Michael Burry thinks about Apple now"), UNIVERSE, []
    )
    assert result == (KIND_CONTEXT, "AAPL", None)


def test_verb_before_name_is_not_a_call():
    # "analyst bearish on TSLA, unlike Burry" must not become a Burry call.
    result = classify_mention(
        mention("Analyst bearish on TSLA, unlike Michael Burry"), UNIVERSE, []
    )
    assert result == (KIND_CONTEXT, "TSLA", None)


def test_name_missing_from_title_is_unusable():
    assert classify_mention(mention("Apple hits record high"), UNIVERSE, []) is None


def test_two_companies_in_title_is_ambiguous_and_unusable():
    result = classify_mention(
        mention("Michael Burry buys Apple and Tesla shares"), UNIVERSE, []
    )
    assert result is None


def test_alias_matches_in_title():
    result = classify_mention(
        mention("Dan Loeb adds AAPL position", speaker="Daniel Loeb"),
        UNIVERSE,
        ["Dan Loeb"],
    )
    assert result == (KIND_CALL, "AAPL", "bullish")


def test_resolve_ticker_single_token_name_requires_capitalized_occurrence():
    assert resolve_ticker("Burry cuts price target on everything", UNIVERSE) is None
    # v13 Q4: even capitalized, "Target" is a generic English word — the single-token
    # name channel is gated for TGT (honest miss); the caps TICKER channel stays open.
    assert resolve_ticker("Burry buys Target shares", UNIVERSE) is None
    assert resolve_ticker("Burry buys TGT stake", UNIVERSE) == "TGT"


def test_resolve_ticker_generic_single_token_names_never_resolve():
    """v13 Q4 (v7 backlog fix): the three live false positives — generic capitalized
    headline words resolving to single-token-named tickers SHEL.L / TGT / NXT.L."""
    universe = [
        ("SHEL.L", "Shell plc"),
        ("TGT", "Target Corporation"),
        ("NXT.L", "Next plc"),
    ]
    assert resolve_ticker("Shell shock for oil markets", universe) is None
    assert resolve_ticker("Target prices raised across Wall Street", universe) is None
    assert resolve_ticker("Next week will be decisive for markets", universe) is None


def test_resolve_ticker_full_name_beats_single_token_riding_inside_it():
    """v13 Q4: a single-token match whose word sits INSIDE the one full-name match is
    the same text span, not a second company — but a title genuinely naming a second
    company stays an honest None."""
    universe = [
        ("BAM", "Brookfield Asset Management Ltd."),
        ("BN", "Brookfield Corporation"),  # normalizes to single-token "BROOKFIELD"
        ("NVDA", "Nvidia Corp"),
    ]
    assert resolve_ticker("Brookfield Asset Management raises new fund", universe) == "BAM"
    assert resolve_ticker(
        "Nvidia partners with Brookfield Asset Management", universe
    ) is None


def test_resolve_ticker_symbol_stopwords_never_match():
    assert resolve_ticker("Burry ALL IN ON US stocks", UNIVERSE) is None


def test_resolve_ticker_portal_acronyms_never_resolve_as_ticker():
    # A guard against real tickers that coincidentally equal a media/portal acronym.
    # SINGLE candidate on purpose: with two portal tickers, None would already fall
    # out of ambiguity pooling — here only the stopword gate can produce it.
    assert resolve_ticker(
        "Market wrap via MSN today", [("MSN", "Placeholder One Inc.")]
    ) is None
    assert resolve_ticker(
        "CNBC interview moves markets", [("CNBC", "Placeholder Two Inc.")]
    ) is None


def test_resolve_ticker_company_name_beats_portal_acronym_collision():
    # Live bug 2026-07-15: a headline about "Micron" (not "Micron Technology" verbatim)
    # syndicated with a " - MSN" outlet suffix resolved to ticker MSN instead of MU,
    # because the name channel missed the bare mention and the raw-token channel had
    # no guard against the portal acronym. MU must resolve; MSN must never.
    universe = [
        *UNIVERSE,
        ("MU", "Micron Technology, Inc."),
        ("MSN", "Placeholder Networks Inc."),
    ]
    title = "Micron soars on AI chip demand - MSN"
    assert resolve_ticker(title, universe) == "MU"


def test_resolve_ticker_generic_first_words_never_resolve_via_first_word_rule():
    # "Prime" is PRME's unique first word in the real universe, but it's an ordinary
    # capitalized English word — "Amazon Prime raises subscription prices" must never
    # fire a Prime Medicine alert. With Amazon as a candidate, the headline resolves
    # to AMZN; without it, to nothing at all.
    prme = ("PRME", "Prime Medicine, Inc. - Common Stock")  # raw universe CSV form
    title = "Amazon Prime raises subscription prices"
    assert resolve_ticker(title, [prme]) is None
    assert resolve_ticker(title, [prme, ("AMZN", "Amazon.com, Inc.")]) == "AMZN"
    # Full-name mentions of a guarded company still resolve — the guard only closes
    # the bare-first-word shortcut, not the name channel; the listing tail must not
    # block the match (exercised in raw CSV form on purpose).
    assert resolve_ticker("Prime Medicine reports trial data", [prme]) == "PRME"


def test_resolve_ticker_tail_stripped_generic_name_keeps_two_word_form():
    # Tail stripping must not collapse "City Holding Company - Common Stock" to the
    # bare generic token "CITY": the single-token branch has no generic-word gate, so
    # every title-case "New York City ..." headline would fire a CHCO mention. The
    # kept two-word form ("CITY HOLDING") still matches real coverage of the company.
    chco = ("CHCO", "City Holding Company - Common Stock")
    assert resolve_ticker(
        "Michael Burry warns New York City office market is doomed", [chco]
    ) is None
    assert resolve_ticker("City Holding Company beats estimates", [chco]) == "CHCO"


def test_resolve_ticker_strips_no_dash_listing_tail():
    # NASDAQ tails also occur without the " - " separator; truncating at the marker
    # exposes fresh trailing suffixes ("... Inc. Class A") that must be re-stripped
    # before the full-name match. "Select" is a guarded first word, so only the full
    # name can produce this hit.
    wttr = ("WTTR", "Select Water Solutions, Inc. Class A common stock")
    assert resolve_ticker("Select Water Solutions wins contract", [wttr]) == "WTTR"


# --- strict resolve channel (P2a statement backfill, evidence/backfill_statements.py) --


def test_resolve_ticker_strict_still_allows_the_literal_full_name_match():
    universe = [("MU", "Micron Technology, Inc.")]
    title = "Micron Technology reports record earnings"
    assert resolve_ticker(title, universe) == "MU"
    assert resolve_ticker(title, universe, strict=True) == "MU"


def test_resolve_ticker_strict_disables_the_distinguishing_first_word_channel():
    # Non-strict: "Micron" alone resolves via the first-word channel (no other
    # tracked company starts with "Micron"). Strict requires the full name.
    universe = [("MU", "Micron Technology, Inc.")]
    title = "Micron soars on AI chip demand"
    assert resolve_ticker(title, universe) == "MU"
    assert resolve_ticker(title, universe, strict=True) is None


def test_resolve_ticker_strict_disables_the_single_token_name_channel():
    # Live P2a fabrication: "Via @Breitbart" resolved to VIIA3.SA under non-strict
    # matching via the single-token "capitalized occurrence" channel -- "Via" is a
    # real (if unfortunate) single-word company name, not curated into
    # `_GENERIC_FIRST_WORDS`, and ordinary prose capitalizes it constantly (sentence
    # starts, "Via @handle" citations). Strict drops this channel entirely.
    universe = [("VIA", "Via Inc.")]  # normalizes to the bare single token "VIA"
    title = "Via @Breitbart, the story broke this morning"
    assert resolve_ticker(title, universe) == "VIA"
    assert resolve_ticker(title, universe, strict=True) is None


def test_resolve_ticker_strict_disables_the_raw_caps_token_channel():
    # Live P2a fabrication: "the market goes UP" resolved to Wheels Up (ticker "UP")
    # purely via the raw all-caps ticker-token fallback -- a stray capitalized word
    # in unedited prose, not a real mention.
    universe = [("UP", "Wheels Up Experience Inc.")]
    title = "I think the market goes UP from here"
    assert resolve_ticker(title, universe) == "UP"
    assert resolve_ticker(title, universe, strict=True) is None


def test_resolve_ticker_strict_default_is_false_and_unchanged():
    universe = [("TGT", "Target Corporation")]
    title = "Burry buys TGT stake"
    assert resolve_ticker(title, universe) == resolve_ticker(title, universe, strict=False)
    assert resolve_ticker(title, universe) == "TGT"


def test_classify_mention_threads_strict_through_to_resolve_ticker():
    universe = [("VIA", "Via Inc.")]
    hit = mention("Michael Burry says Via is a great company")
    assert classify_mention(hit, universe, [])[1] == "VIA"
    assert classify_mention(hit, universe, [], strict=True) is None


def test_classify_mention_masks_speaker_name_before_ticker_resolution():
    # The speaker attribution must never double as company evidence: "Bill Ackman"
    # fabricated a BILL Holdings ledger call, "Stanley Druckenmiller" a Stanley
    # Black & Decker context mention (live regression, B5 round 5).
    universe = [
        ("BILL", "BILL Holdings, Inc. - Common Stock"),
        ("SWK", "Stanley Black & Decker"),
        ("NKE", "Nike, Inc."),
    ]
    fabricated_call = mention(
        "Bill Ackman buys more shares of an undisclosed company", speaker="Bill Ackman"
    )
    assert classify_mention(fabricated_call, universe, []) is None
    fabricated_context = mention(
        "Stanley Druckenmiller sees trouble ahead for markets",
        speaker="Stanley Druckenmiller",
    )
    assert classify_mention(fabricated_context, universe, []) is None
    # Positive control: with the speaker masked, a genuine company mention still
    # resolves — even one sharing the speaker's first name as its ticker.
    genuine = mention("Bill Ackman buys BILL Holdings stock", speaker="Bill Ackman")
    assert classify_mention(genuine, universe, []) == (KIND_CALL, "BILL", "bullish")
    nike = mention("Bill Ackman buys Nike shares", speaker="Bill Ackman")
    assert classify_mention(nike, universe, []) == (KIND_CALL, "NKE", "bullish")


# --- collector -----------------------------------------------------------------


def _fake_get(responses: dict[str, str]):
    def get(url: str) -> str:
        for fragment, xml in responses.items():
            if fragment in url:
                return xml
        raise AssertionError(f"unexpected url {url}")

    return get


def test_collect_voices_builds_events_with_weekly_keys():
    xml = rss([("Michael Burry buys Apple shares", "Sat, 12 Jul 2026 09:30:00 GMT")])
    empty = rss([])
    result = collect_voices(
        now="2026-07-13T12:00:00+00:00",
        universe=UNIVERSE,
        persons={"Michael Burry": []},
        http_get=_fake_get({"news.google.com": xml, "bing.com": empty}),
    )
    assert result.status == STATUS_OK
    assert len(result.events) == 1
    event = result.events[0]
    assert event.source == SOURCE_VOICE
    assert event.ticker == "AAPL"
    assert event.event_key == "michael-burry-bullish-2026w29"
    assert event.details["kind"] == KIND_CALL
    assert event.details["speaker"] == "Michael Burry"


def test_collect_voices_drops_stale_headlines():
    xml = rss([("Michael Burry buys Apple shares", "Tue, 01 Jul 2025 09:30:00 GMT")])
    result = collect_voices(
        now="2026-07-13T12:00:00+00:00",
        universe=UNIVERSE,
        persons={"Michael Burry": []},
        http_get=_fake_get({"news.google.com": xml, "bing.com": xml}),
    )
    assert result.status == STATUS_OK
    assert result.events == []


def test_collect_voices_total_feed_failure_degrades_to_fetch_failed():
    def broken(url: str) -> str:
        raise OSError("offline")

    result = collect_voices(
        now="2026-07-13T12:00:00+00:00",
        universe=UNIVERSE,
        persons={"Michael Burry": []},
        http_get=broken,
    )
    assert result.status == STATUS_FETCH_FAILED
    assert result.events == []


def test_collect_voices_one_feed_failing_keeps_the_other():
    xml = rss([("Michael Burry buys Apple shares", "Sat, 12 Jul 2026 09:30:00 GMT")])

    def get(url: str) -> str:
        if "bing.com" in url:
            raise OSError("offline")
        return xml

    result = collect_voices(
        now="2026-07-13T12:00:00+00:00",
        universe=UNIVERSE,
        persons={"Michael Burry": []},
        http_get=get,
    )
    assert result.status == STATUS_OK
    assert len(result.events) == 1


# --- downstream honesty gates --------------------------------------------------


def voice_event_row(kind: str, direction: str | None = None) -> dict:
    details = {
        "speaker": "Michael Burry",
        "kind": kind,
        "headline": "Michael Burry buys Apple shares",
        "feed": "google-news",
        "published": "2026-07-12",
    }
    if direction:
        details["direction"] = direction
    return {
        "source": SOURCE_VOICE,
        "ticker": "AAPL",
        "event_key": "michael-burry-bullish-2026w29",
        "event_date": "2026-07-12",
        "details": details,
    }


def test_calls_from_events_accepts_only_bullish_voice_calls():
    rows = [
        voice_event_row(KIND_CALL, "bullish"),
        voice_event_row(KIND_CALL_BEARISH, "bearish"),
        voice_event_row(KIND_CONTEXT),
    ]
    calls = calls_from_events(rows)
    assert len(calls) == 1
    assert calls[0].person == "Michael Burry"
    assert calls[0].source == SOURCE_VOICE
    assert calls[0].t0 == "2026-07-12"


def test_ledgerable_events_filters_context_and_bearish_voice_rows():
    from scripts.run_evidence import ledgerable_events

    def event(kind: str | None) -> EvidenceEvent:
        details = {"kind": kind} if kind else {}
        return EvidenceEvent(SOURCE_VOICE, "AAPL", f"k-{kind}", "2026-07-12", details)

    events = [event(None), event(KIND_CALL), event(KIND_CALL_BEARISH), event(KIND_CONTEXT)]
    kept = ledgerable_events(events)
    assert [e.event_key for e in kept] == ["k-None", "k-call"]


def test_dedupe_mentions_ignores_trailing_outlet_suffix():
    first = mention("Michael Burry buys Apple stock - Yahoo Finance")
    other_outlet = mention("Michael Burry buys Apple stock - MSN")
    assert dedupe_mentions([first, other_outlet]) == [first]
