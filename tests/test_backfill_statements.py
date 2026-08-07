"""Statement backfill: Trump's own public statements (Twitter archive + Truth Social
archive) run through voices.classify_mention (STRICT mode) -> HistoricalEvents.

Fixture rows for `events_from_statement_rows` use the NORMALIZED shape the two
platform-specific CSV parsers produce (platform/post_id/text/published) — see the
module docstring of `evidence/backfill_statements.py` for the two archives' REAL,
live-verified column layouts (2026-08-07) that `_rows_from_twitter_csv` /
`_rows_from_truth_social_csv` parse into that shape.

The test universe uses MULTI-WORD company names on purpose: `events_from_statement_rows`
calls `classify_mention` with `strict=True` (P2a review fix, 2026-08-07 — full-corpus run
produced 44 fabricated events via the single-token-name and raw-caps-token channels), so
only the literal full-company-name-as-substring channel resolves a ticker. A single-token
name ("Apple Inc." -> "APPLE") is deliberately kept as its OWN small universe
(`SINGLE_TOKEN_UNIVERSE`) to prove that channel is now unreachable from this module.
"""
from __future__ import annotations

import pytest

from equity_scout.evidence.backfill_statements import (
    TRUTH_SOCIAL_ARCHIVE_CSV_URL,
    TWITTER_ARCHIVE_CSV_URLS,
    _rows_from_truth_social_csv,
    _rows_from_twitter_csv,
    backfill_statements,
    events_from_statement_rows,
)
from equity_scout.evidence.base import SOURCE_STATEMENT
from equity_scout.evidence.historical_storage import record_historical_events, unresolved_events

NOW = "2026-08-07T12:00:00+00:00"

# Normalize to multi-word forms ("APPLE TECHNOLOGY", "TESLA MOTORS", "BOEING AEROSPACE")
# so the strict full-name channel (the only one left active) can resolve them.
UNIVERSE = [
    ("AAPL", "Apple Technology Corp"),
    ("TSLA", "Tesla Motors Corp"),
    ("BA", "Boeing Aerospace Corp"),
]
# Normalizes to the bare single token "APPLE" -- used to prove the single-token
# "capitalized occurrence" channel is unreachable from this module under strict.
SINGLE_TOKEN_UNIVERSE = [("AAPL", "Apple Inc.")]


def _row(**overrides) -> dict:
    row = {
        "platform": "twitter",
        "post_id": "1698308935",
        "text": "Donald Trump buys Apple Technology shares, a great American company!",
        "published": "2018-05-04T13:54:00",
    }
    row.update(overrides)
    return row


def _counts(**overrides) -> dict:
    base = {
        "rows": 0, "calls": 0, "bearish_calls": 0, "context": 0, "unclassified": 0,
        "malformed": 0, "retweets": 0, "duplicate_text": 0, "kept": 0,
    }
    base.update(overrides)
    return base


# --- events_from_statement_rows --------------------------------------------------


def test_bullish_call_is_kept_with_full_details():
    events, counts = events_from_statement_rows([_row()], UNIVERSE, [])
    assert len(events) == 1
    event = events[0]
    assert event.source == SOURCE_STATEMENT
    assert event.person == "Donald Trump"
    assert event.ticker == "AAPL"
    assert event.event_key == "donald-trump-1698308935"
    # t0 is the DATE part only (Decision 10) -- the full timestamp survives in details.
    assert event.t0 == "2018-05-04"
    assert event.details["published"] == "2018-05-04T13:54:00"
    assert event.details["platform"] == "twitter"
    assert event.details["direction"] == "bullish"
    assert event.details["matched_phrase"] == "buys"
    assert counts == _counts(rows=1, calls=1, kept=1)


def test_bearish_call_is_kept_and_counted_separately():
    row = _row(text="Donald Trump sells Tesla Motors stock after disappointing earnings")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert len(events) == 1
    assert events[0].ticker == "TSLA"
    assert events[0].details["direction"] == "bearish"
    assert events[0].details["matched_phrase"] == "sells"
    assert counts == _counts(rows=1, bearish_calls=1, kept=1)


def test_third_person_self_reference_matches_via_last_name_fallback():
    """Trump's own archived statements are mostly third-person self-references
    ("Donald Trump reads Top Ten..."), never first-person -- the deterministic
    classifier still fires because `voices._name_in_title` auto-adds the bare
    surname ("Trump") as a match candidate whenever it is longer than 3 chars."""
    row = _row(text="President Trump buys Boeing Aerospace shares, a beautiful plane maker")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert len(events) == 1
    assert events[0].ticker == "BA"
    assert counts == _counts(rows=1, calls=1, kept=1)


def test_context_mention_without_direction_is_counted_not_stored():
    row = _row(text="Donald Trump talks about Apple Technology during rally")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert events == []
    assert counts == _counts(rows=1, context=1)


def test_ambiguous_two_company_title_is_counted_unclassified():
    row = _row(text="Donald Trump buys Apple Technology and Tesla Motors shares")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert events == []
    assert counts == _counts(rows=1, unclassified=1)


def test_no_direction_phrase_at_all_is_context_not_unclassified():
    row = _row(text="Donald Trump owns an Apple Technology product")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert events == []
    # "owns" is not in the closed BULLISH/BEARISH phrase lists -> context (has a
    # resolvable ticker, no verb) rather than unclassified (no ticker at all).
    assert counts == _counts(rows=1, context=1)


def test_name_not_in_text_is_unclassified():
    row = _row(text="Apple Technology hits a record high today")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert events == []
    assert counts == _counts(rows=1, unclassified=1)


def test_alias_widens_name_matching():
    row = _row(text="The Donald buys Apple Technology shares")
    events, counts = events_from_statement_rows([row], UNIVERSE, ["The Donald"])
    assert len(events) == 1
    assert events[0].ticker == "AAPL"


def test_event_key_uses_person_slug_and_post_id():
    row = _row(post_id="999")
    events, _ = events_from_statement_rows([row], UNIVERSE, [], person="Donald Trump")
    assert events[0].event_key == "donald-trump-999"


def test_default_person_is_donald_trump():
    events, _ = events_from_statement_rows([_row()], UNIVERSE, [])
    assert events[0].person == "Donald Trump"


def test_truth_social_platform_flows_through_to_details():
    row = _row(
        platform="truth_social",
        text="Donald Trump buys Apple Technology shares",
        published="2022-05-02T23:12:54.339Z",
    )
    events, _ = events_from_statement_rows([row], UNIVERSE, [])
    assert events[0].details["platform"] == "truth_social"
    # t0 truncation must work identically for the millisecond-precision Truth Social
    # timestamp format, not just the Twitter one.
    assert events[0].t0 == "2022-05-02"
    assert events[0].details["published"] == "2022-05-02T23:12:54.339Z"


def test_malformed_rows_are_counted_not_crashing():
    rows = [
        None,
        7,
        "not a dict",
        {"platform": "twitter"},  # missing text/post_id/published
        {"platform": "twitter", "post_id": "1", "text": "", "published": "2018-01-01"},
        {"platform": "twitter", "post_id": "1", "text": "x", "published": ""},
        _row(),
    ]
    events, counts = events_from_statement_rows(rows, UNIVERSE, [])
    assert len(events) == 1
    assert counts == _counts(rows=7, malformed=6, calls=1, kept=1)


def test_row_counter_is_a_complete_partition():
    rows = [
        _row(post_id="1"),  # call
        _row(post_id="2", text="Donald Trump sells Tesla Motors stock"),  # bearish call
        _row(post_id="3", text="Donald Trump talks about Apple Technology"),  # context
        _row(post_id="4", text="Apple Technology hits a record high"),  # unclassified
        _row(post_id="5", text="RT @nytimes: Apple Technology set to soar"),  # retweet
        _row(post_id="6"),  # exact duplicate of post_id 1's text -> duplicate_text
        None,  # malformed
    ]
    events, counts = events_from_statement_rows(rows, UNIVERSE, [])
    assert counts["rows"] == 7
    partition = (
        counts["calls"] + counts["bearish_calls"] + counts["context"]
        + counts["unclassified"] + counts["malformed"]
        + counts["retweets"] + counts["duplicate_text"]
    )
    assert partition == counts["rows"]
    assert counts["kept"] == counts["calls"] + counts["bearish_calls"]
    assert len(events) == counts["kept"]
    assert counts == _counts(
        rows=7, calls=1, bearish_calls=1, context=1, unclassified=1, malformed=1,
        retweets=1, duplicate_text=1, kept=2,
    )


# --- strict resolve channel wiring (P2a review fix, 2026-08-07) --------------------


def test_single_token_company_name_never_resolves_under_this_module():
    """Regression lock for the strict wiring itself: before this fix, "Apple" alone
    resolved AAPL via voices' single-token "capitalized occurrence" channel -- exactly
    the class of fabrication the full-corpus review found (e.g. "Via @Breitbart" ->
    VIIA3.SA). `events_from_statement_rows` must call classify_mention with
    strict=True, so this now falls to `unclassified`, not a call."""
    row = _row(text="Donald Trump buys Apple shares")
    events, counts = events_from_statement_rows([row], SINGLE_TOKEN_UNIVERSE, [])
    assert events == []
    assert counts == _counts(rows=1, unclassified=1)


def test_earliest_direction_wins_when_both_bullish_and_bearish_phrases_are_present():
    """A single company mentioned once, but both a bullish and a bearish phrase
    referencing it appear in the same statement -- the earliest phrase after the name
    decides (same tie-break as voices._direction_after), and the reported
    matched_phrase must agree with that decision, not the later phrase."""
    row = _row(text="Donald Trump buys Apple Technology then sells it days later")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert len(events) == 1
    assert events[0].ticker == "AAPL"
    assert events[0].details["direction"] == "bullish"
    assert events[0].details["matched_phrase"] == "buys"
    assert counts == _counts(rows=1, calls=1, kept=1)


# --- retweet filter -----------------------------------------------------------------


def test_retweet_with_at_prefix_is_counted_and_never_classified():
    row = _row(text="RT @nytimes: Apple Technology set to soar this quarter, buys everywhere")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert events == []
    assert counts == _counts(rows=1, retweets=1)


def test_retweet_with_colon_prefix_is_counted():
    row = _row(text="RT: Someone said Donald Trump buys Apple Technology shares")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert events == []
    assert counts == _counts(rows=1, retweets=1)


def test_retweet_prefix_check_tolerates_leading_whitespace():
    row = _row(text="  RT @nytimes: Apple Technology set to soar, Trump buys in")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert events == []
    assert counts["retweets"] == 1


def test_text_merely_containing_rt_is_not_treated_as_a_retweet():
    # "Retweet" and mid-sentence "RT" must not false-positive the prefix check.
    row = _row(text="Donald Trump buys Apple Technology -- Retweet if you agree, RT!")
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert len(events) == 1
    assert counts["retweets"] == 0
    assert counts["calls"] == 1


def test_retweet_of_a_third_partys_bullish_claim_is_never_attributed_to_trump():
    """Live P2a fabrication: an RT of `@JerryFalwellJr`'s own bullish claim about the
    NYT became a Trump-bullish-on-NYT call. The retweet filter must catch this before
    classify_mention ever sees it, regardless of what the quoted text says."""
    row = _row(
        text=(
            "RT @JerryFalwellJr: Donald Trump buys Apple Technology shares, "
            "NYT admits it too"
        )
    )
    events, counts = events_from_statement_rows([row], UNIVERSE, [])
    assert events == []
    assert counts == _counts(rows=1, retweets=1)


# --- exact-text dedupe within batch --------------------------------------------------


def test_exact_text_duplicate_within_batch_is_counted_and_skipped():
    """Live P2a finding: 2,497 rows in the real corpus are exact text repeats, mostly
    self-RTs. Two DIFFERENT posts (different post_id/platform) with byte-identical
    text must collapse to one classified event, first kept."""
    first = _row(post_id="1")
    duplicate = _row(post_id="2", platform="truth_social")
    events, counts = events_from_statement_rows([first, duplicate], UNIVERSE, [])
    assert len(events) == 1
    assert events[0].event_key == "donald-trump-1"
    assert counts == _counts(rows=2, calls=1, kept=1, duplicate_text=1)


def test_non_identical_texts_are_not_deduped():
    first = _row(post_id="1", text="Donald Trump buys Apple Technology shares")
    second = _row(post_id="2", text="Donald Trump buys Apple Technology shares today")
    events, counts = events_from_statement_rows([first, second], UNIVERSE, [])
    assert len(events) == 2
    assert counts["duplicate_text"] == 0


# --- _rows_from_twitter_csv -------------------------------------------------------


TWITTER_CSV_HEADER = "ID, Time, Tweet URL, Tweet Text"


def test_rows_from_twitter_csv_parses_the_verified_real_layout():
    """Verified layout (live download 2026-08-07): comma+SPACE delimiter, `ID` is the
    constant handle (not a real id -- the post id lives at the tail of the URL), and
    `Tweet Text` is wrapped in a literal quote character that is NOT csv quoting."""
    csv_text = (
        f"{TWITTER_CSV_HEADER}\n"
        '@realDonaldTrump, 2009-05-04 13:54,'
        ' https://twitter.com/realDonaldTrump/status/1698308935,'
        ' "Be sure to tune in and watch Donald Trump on Late Night!"\n'
    )
    rows, counts = _rows_from_twitter_csv(csv_text)
    assert len(rows) == 1
    row = rows[0]
    assert row["platform"] == "twitter"
    assert row["post_id"] == "1698308935"
    assert row["text"] == "Be sure to tune in and watch Donald Trump on Late Night!"
    assert row["published"] == "2009-05-04T13:54:00"
    assert counts == {"malformed": 0, "no_text": 0}


def test_rows_from_twitter_csv_handles_embedded_commas_in_tweet_text():
    """A real, live-verified quirk: the source is NOT proper RFC CSV for its last
    column, so a tweet with an internal comma must still parse as ONE text field via
    the maxsplit(', ', 3) rule rather than spilling into extra columns."""
    csv_text = (
        f"{TWITTER_CSV_HEADER}\n"
        '@realDonaldTrump, 2009-05-13 12:38,'
        ' https://twitter.com/realDonaldTrump/status/1786560616,'
        ' "Listen to an interview with Donald Trump discussing his new book,'
        ' Think Like A Champion"\n'
    )
    rows, counts = _rows_from_twitter_csv(csv_text)
    assert len(rows) == 1
    assert rows[0]["text"] == (
        "Listen to an interview with Donald Trump discussing his new book,"
        " Think Like A Champion"
    )
    assert counts["malformed"] == 0


def test_rows_from_twitter_csv_counts_unparseable_lines_as_malformed():
    csv_text = f"{TWITTER_CSV_HEADER}\nthis line has no commas at all\n"
    rows, counts = _rows_from_twitter_csv(csv_text)
    assert rows == []
    assert counts["malformed"] == 1


def test_rows_from_twitter_csv_counts_url_without_status_id_as_malformed():
    csv_text = (
        f"{TWITTER_CSV_HEADER}\n"
        '@realDonaldTrump, 2009-05-04 13:54, https://twitter.com/realDonaldTrump,'
        ' "no status id in this url"\n'
    )
    rows, counts = _rows_from_twitter_csv(csv_text)
    assert rows == []
    assert counts["malformed"] == 1


def test_rows_from_twitter_csv_counts_unparseable_timestamp_as_malformed():
    csv_text = (
        f"{TWITTER_CSV_HEADER}\n"
        '@realDonaldTrump, not-a-date,'
        ' https://twitter.com/realDonaldTrump/status/123, "some text"\n'
    )
    rows, counts = _rows_from_twitter_csv(csv_text)
    assert rows == []
    assert counts["malformed"] == 1


def test_rows_from_twitter_csv_counts_empty_quoted_text_as_no_text():
    """A row whose Tweet Text column is a literal empty-quoted string ("") is
    structurally valid but has nothing to classify -- distinct from `malformed`."""
    csv_text = (
        f"{TWITTER_CSV_HEADER}\n"
        '@realDonaldTrump, 2009-05-04 13:54,'
        ' https://twitter.com/realDonaldTrump/status/1, ""\n'
    )
    rows, counts = _rows_from_twitter_csv(csv_text)
    assert rows == []
    assert counts == {"malformed": 0, "no_text": 1}


def test_rows_from_twitter_csv_skips_blank_lines():
    csv_text = f"{TWITTER_CSV_HEADER}\n\n"
    rows, counts = _rows_from_twitter_csv(csv_text)
    assert rows == []
    assert counts == {"malformed": 0, "no_text": 0}


def test_rows_from_twitter_csv_raises_on_renamed_header():
    """Positional parsing has no per-column name check like the Truth Social reader's
    `_TRUTH_SOCIAL_REQUIRED_COLUMNS` -- the header line itself is the only guard
    against a silently reordered/renamed column producing wrong-but-plausible data."""
    csv_text = "ID, Timestamp, URL, Text\nsomething\n"
    with pytest.raises(ValueError):
        _rows_from_twitter_csv(csv_text)


def test_rows_from_twitter_csv_raises_on_empty_input():
    with pytest.raises(ValueError):
        _rows_from_twitter_csv("")


def test_rows_from_twitter_csv_strips_leading_bom():
    csv_text = (
        "\ufeff" + f"{TWITTER_CSV_HEADER}\n"
        '@realDonaldTrump, 2009-05-04 13:54,'
        ' https://twitter.com/realDonaldTrump/status/1, "hello"\n'
    )
    rows, counts = _rows_from_twitter_csv(csv_text)
    assert len(rows) == 1
    assert counts == {"malformed": 0, "no_text": 0}


def test_rows_from_twitter_csv_does_not_truncate_text_at_unicode_line_separator():
    """`str.splitlines()` also breaks on U+2028 (LINE SEPARATOR); a real tweet
    containing one would otherwise be silently truncated mid-text."""
    csv_text = (
        f"{TWITTER_CSV_HEADER}\n"
        '@realDonaldTrump, 2009-05-04 13:54,'
        ' https://twitter.com/realDonaldTrump/status/1,'
        ' "Part one Part two"\n'
    )
    rows, counts = _rows_from_twitter_csv(csv_text)
    assert len(rows) == 1
    assert rows[0]["text"] == "Part one Part two"
    assert counts == {"malformed": 0, "no_text": 0}

def test_rows_from_twitter_csv_unescapes_html_entities():
    """Symmetric with the Truth Social parser: measured on 2,589 real Twitter archive
    rows carrying HTML entities (e.g. "Tariffs &amp;amp; Trade")."""
    csv_text = (
        f"{TWITTER_CSV_HEADER}\n"
        '@realDonaldTrump, 2009-05-04 13:54,'
        ' https://twitter.com/realDonaldTrump/status/1,'
        ' "Tariffs &amp; Trade with Apple Technology"\n'
    )
    rows, _ = _rows_from_twitter_csv(csv_text)
    assert rows[0]["text"] == "Tariffs & Trade with Apple Technology"


# --- _rows_from_truth_social_csv ---------------------------------------------------


def _ts_csv(rows_csv: str) -> str:
    header = "id,created_at,content,url,media,replies_count,reblogs_count,favourites_count"
    return f"{header}\n{rows_csv}"


def test_rows_from_truth_social_csv_parses_the_verified_real_layout():
    csv_text = _ts_csv(
        '116507513607934090,2026-05-02T23:12:54.339Z,'
        '"Donald Trump buys Apple Technology shares",'
        'https://truthsocial.com/@realDonaldTrump/116507513607934090,,10,20,30\n'
    )
    rows, counts = _rows_from_truth_social_csv(csv_text)
    assert len(rows) == 1
    row = rows[0]
    assert row["platform"] == "truth_social"
    assert row["post_id"] == "116507513607934090"
    assert row["text"] == "Donald Trump buys Apple Technology shares"
    assert row["published"] == "2026-05-02T23:12:54.339Z"
    assert counts == {"malformed": 0, "no_text": 0}


def test_rows_from_truth_social_csv_counts_media_only_posts_as_no_text():
    """~17% of the real archive (verified 2026-08-07) is an image/video post with an
    empty `content` column -- a real, expected shape, not a defect."""
    csv_text = _ts_csv(
        "116502923327437911,2026-05-02T03:45:32.282Z,,"
        "https://truthsocial.com/@realDonaldTrump/116502923327437911,"
        "https://example.com/img.jpg,10,20,30\n"
    )
    rows, counts = _rows_from_truth_social_csv(csv_text)
    assert rows == []
    assert counts == {"malformed": 0, "no_text": 1}


def test_rows_from_truth_social_csv_handles_embedded_commas_via_proper_quoting():
    csv_text = _ts_csv(
        '1,2026-05-02T23:12:54.339Z,'
        '"Donald Trump buys Apple, Tesla, and Boeing shares",'
        "https://truthsocial.com/@realDonaldTrump/1,,0,0,0\n"
    )
    rows, _ = _rows_from_truth_social_csv(csv_text)
    assert rows[0]["text"] == "Donald Trump buys Apple, Tesla, and Boeing shares"


def test_rows_from_truth_social_csv_raises_on_missing_required_column():
    """Schema drift on a READ column must fail loudly, never silently yield zero
    rows and look like a quiet, successful empty run (same convention as
    backfill_form4.py's `_REQUIRED_COLUMNS` guard)."""
    csv_text = "id,created_at,url\n1,2026-05-02T23:12:54.339Z,https://x\n"
    with pytest.raises(ValueError):
        _rows_from_truth_social_csv(csv_text)


def test_rows_from_truth_social_csv_strips_leading_bom():
    csv_text = "\ufeff" + _ts_csv('1,2026-05-02T23:12:54.339Z,"hello",https://x,,0,0,0\n')
    rows, _ = _rows_from_truth_social_csv(csv_text)
    assert len(rows) == 1
    assert rows[0]["text"] == "hello"


def test_rows_from_truth_social_csv_unescapes_html_entities():
    csv_text = _ts_csv(
        '1,2026-05-02T23:12:54.339Z,'
        '"Tariffs &amp; Trade with Apple Technology",'
        "https://x,,0,0,0\n"
    )
    rows, _ = _rows_from_truth_social_csv(csv_text)
    assert rows[0]["text"] == "Tariffs & Trade with Apple Technology"


# --- backfill_statements -----------------------------------------------------------


TWITTER_BF_CSV = (
    f"{TWITTER_CSV_HEADER}\n"
    '@realDonaldTrump, 2018-05-04 13:54,'
    ' https://twitter.com/realDonaldTrump/status/1,'
    ' "Donald Trump buys Apple Technology shares"\n'
)
TWITTER_IN_CSV = (
    f"{TWITTER_CSV_HEADER}\n"
    '@realDonaldTrump, 2019-05-04 13:54,'
    ' https://twitter.com/realDonaldTrump/status/2,'
    ' "Donald Trump sells Tesla Motors stock"\n'
)
TRUTH_SOCIAL_CSV = _ts_csv(
    "3,2022-05-02T23:12:54.339Z,"
    '"Donald Trump buys Boeing Aerospace shares",'
    "https://truthsocial.com/@realDonaldTrump/3,,0,0,0\n"
)


def _fake_get(responses: dict[str, str]):
    def get(url: str) -> str:
        if url in responses:
            return responses[url]
        raise AssertionError(f"unexpected url: {url}")

    return get


def _all_sources_ok() -> dict[str, str]:
    twitter_bf_url, twitter_in_url = TWITTER_ARCHIVE_CSV_URLS
    return {
        twitter_bf_url: TWITTER_BF_CSV,
        twitter_in_url: TWITTER_IN_CSV,
        TRUTH_SOCIAL_ARCHIVE_CSV_URL: TRUTH_SOCIAL_CSV,
    }


def test_backfill_statements_records_events_and_reports_counts(tmp_path):
    db = str(tmp_path / "test.db")
    counts = backfill_statements(
        db, now=NOW, http_get=_fake_get(_all_sources_ok()), universe=UNIVERSE
    )
    assert counts["sources_fetched"] == 3
    assert counts["sources_failed"] == 0
    assert counts["source_errors"] == []
    assert counts["events_new"] == 3
    assert counts["events_seen"] == 3
    assert counts["calls"] == 2
    assert counts["bearish_calls"] == 1
    rows = unresolved_events(db)
    assert {r["ticker"] for r in rows} == {"AAPL", "TSLA", "BA"}
    assert all(r["source"] == SOURCE_STATEMENT for r in rows)
    # t0 is date-only in storage too, not just in the dataclass before insertion.
    assert all(len(r["t0"]) == len("2018-05-04") for r in rows)


def test_backfill_statements_dead_mirror_is_a_counted_skip_not_a_crash(tmp_path):
    db = str(tmp_path / "test.db")
    responses = _all_sources_ok()
    twitter_bf_url, _ = TWITTER_ARCHIVE_CSV_URLS

    def get(url: str) -> str:
        if url == twitter_bf_url:
            raise OSError("mirror gone")
        return responses[url]

    counts = backfill_statements(db, now=NOW, http_get=get, universe=UNIVERSE)
    assert counts["sources_fetched"] == 2
    assert counts["sources_failed"] == 1
    assert len(counts["source_errors"]) == 1
    assert counts["source_errors"][0] == f"{twitter_bf_url}: mirror gone"
    # The two live sources still produce their events -- one dead mirror never
    # aborts the whole run.
    assert counts["events_new"] == 2


def test_backfill_statements_per_platform_counts_reflect_partial_failure(tmp_path):
    """When one Twitter file is dead, ITS per-platform counts/date-range must stay at
    their zero/None defaults while the surviving sources are entirely unaffected --
    no cross-contamination between platforms' bookkeeping."""
    db = str(tmp_path / "test.db")
    responses = _all_sources_ok()
    twitter_bf_url, _ = TWITTER_ARCHIVE_CSV_URLS

    def get(url: str) -> str:
        if url == twitter_bf_url:
            raise OSError("mirror gone")
        return responses[url]

    counts = backfill_statements(db, now=NOW, http_get=get, universe=UNIVERSE)
    # Only the surviving in-office file's one row counts.
    assert counts["twitter_rows"] == 1
    assert counts["twitter_date_min"] == counts["twitter_date_max"] == "2019-05-04T13:54:00"
    # Truth Social is entirely untouched by the Twitter-side failure.
    assert counts["truth_social_rows"] == 1
    assert counts["truth_social_date_min"] == "2022-05-02T23:12:54.339Z"


def test_backfill_statements_schema_drift_is_a_counted_skip_not_a_crash(tmp_path):
    """A source that fetches fine but no longer matches the verified layout (renamed
    column) must degrade to a counted `sources_parse_failed`, never propagate the
    parser's ValueError out of the run and abort the other two sources."""
    db = str(tmp_path / "test.db")
    responses = _all_sources_ok()
    responses[TRUTH_SOCIAL_ARCHIVE_CSV_URL] = "id,created_at\n1,2022-01-01\n"  # missing content

    counts = backfill_statements(db, now=NOW, http_get=_fake_get(responses), universe=UNIVERSE)
    assert counts["sources_fetched"] == 3
    assert counts["sources_parse_failed"] == 1
    assert counts["truth_social_rows"] == 0
    assert len(counts["source_errors"]) == 1
    assert "missing read column" in counts["source_errors"][0]
    # The two Twitter sources still contribute their events.
    assert counts["events_new"] == 2


def test_backfill_statements_all_mirrors_dead_is_a_loud_zero_not_silent(tmp_path):
    db = str(tmp_path / "test.db")

    def get(url: str) -> str:
        raise OSError("offline")

    counts = backfill_statements(db, now=NOW, http_get=get, universe=UNIVERSE)
    assert counts["sources_fetched"] == 0
    assert counts["sources_failed"] == 3
    assert len(counts["source_errors"]) == 3
    assert counts["events_new"] == 0
    assert counts["rows"] == 0


def test_backfill_statements_no_text_counts_reach_aggregates(tmp_path):
    """Verifies the flow-through from the parser's own `no_text` counter up to the
    per-platform aggregate `backfill_statements` returns -- not just the parser's own
    unit-level return value."""
    db = str(tmp_path / "test.db")
    responses = _all_sources_ok()
    responses[TRUTH_SOCIAL_ARCHIVE_CSV_URL] = _ts_csv(
        "3,2022-05-02T23:12:54.339Z,"
        '"Donald Trump buys Boeing Aerospace shares",'
        "https://truthsocial.com/@realDonaldTrump/3,,0,0,0\n"
        "4,2022-05-03T00:00:00.000Z,,"
        "https://truthsocial.com/@realDonaldTrump/4,https://x/img.jpg,0,0,0\n"
    )
    counts = backfill_statements(db, now=NOW, http_get=_fake_get(responses), universe=UNIVERSE)
    assert counts["truth_social_no_text"] == 1
    assert counts["truth_social_rows"] == 1  # the media-only post is not a row
    assert counts["twitter_no_text"] == 0


def test_backfill_statements_dedupes_within_batch_on_shared_post_id(tmp_path):
    """A mirror-side data-quality glitch republishing the same post id twice in one
    fetch must still collapse to ONE stored fact via `record_historical_events`'
    INSERT OR IGNORE -- the same (source, ticker, event_key) rule used everywhere
    else in `historical_events`, exercised here within a single batch rather than
    across reruns."""
    db = str(tmp_path / "test.db")
    duplicated_bf = (
        f"{TWITTER_CSV_HEADER}\n"
        '@realDonaldTrump, 2018-05-04 13:54,'
        ' https://twitter.com/realDonaldTrump/status/1,'
        ' "Donald Trump buys Apple Technology shares"\n'
        '@realDonaldTrump, 2018-05-04 14:00,'
        ' https://twitter.com/realDonaldTrump/status/1,'
        ' "Donald Trump buys Apple Technology shares extra"\n'
    )
    responses = _all_sources_ok()
    twitter_bf_url, _ = TWITTER_ARCHIVE_CSV_URLS
    responses[twitter_bf_url] = duplicated_bf

    counts = backfill_statements(db, now=NOW, http_get=_fake_get(responses), universe=UNIVERSE)
    assert counts["twitter_rows"] == 3  # 2 duplicated-id bf rows + 1 in-office row
    assert counts["events_seen"] == 4  # both same-id rows classify independently (different text)
    assert counts["events_new"] == 3  # but collapse to one AAPL row in storage
    rows = unresolved_events(db)
    assert len(rows) == 3
    assert sorted(r["ticker"] for r in rows) == ["AAPL", "BA", "TSLA"]


def test_backfill_statements_dedupes_on_rerun(tmp_path):
    db = str(tmp_path / "test.db")
    get = _fake_get(_all_sources_ok())
    first = backfill_statements(db, now=NOW, http_get=get, universe=UNIVERSE)
    assert first["events_new"] == 3
    second = backfill_statements(db, now=NOW, http_get=get, universe=UNIVERSE)
    assert second["events_new"] == 0
    assert second["events_seen"] == 3


def test_backfill_statements_surfaces_per_platform_coverage(tmp_path):
    """Task 7's report needs the 01/2021-2022 platform-ban gap as data, not prose --
    surfaced here as per-platform row counts and date ranges."""
    db = str(tmp_path / "test.db")
    counts = backfill_statements(
        db, now=NOW, http_get=_fake_get(_all_sources_ok()), universe=UNIVERSE
    )
    assert counts["twitter_rows"] == 2
    assert counts["truth_social_rows"] == 1
    assert counts["twitter_date_min"] == "2018-05-04T13:54:00"
    assert counts["twitter_date_max"] == "2019-05-04T13:54:00"
    assert counts["truth_social_date_min"] == "2022-05-02T23:12:54.339Z"
    assert counts["truth_social_date_max"] == "2022-05-02T23:12:54.339Z"


def test_backfill_statements_writes_via_record_historical_events(tmp_path, monkeypatch):
    """Proves the actual storage call, not a hand-rolled INSERT -- a regression in
    either module must show up here."""
    db = str(tmp_path / "test.db")
    from equity_scout.evidence import backfill_statements as mod

    calls = []
    original = record_historical_events

    def spy(db_path, events, *, now):
        calls.append((db_path, len(events), now))
        return original(db_path, events, now=now)

    monkeypatch.setattr(mod, "record_historical_events", spy)
    backfill_statements(db, now=NOW, http_get=_fake_get(_all_sources_ok()), universe=UNIVERSE)
    assert calls == [(db, 3, NOW)]
