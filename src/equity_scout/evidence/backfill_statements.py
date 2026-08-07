"""Statement backfill: Donald Trump's OWN public statements (Twitter 2009-2021, Truth
Social 2022->), classified via the existing `voices.classify_mention` (name-before-verb,
closed direction lists, `resolve_ticker` never guesses) into `historical_events` (P2a).

Both source CSVs are best-effort COMMUNITY MIRRORS, not an official archive -- either can
go dark, be renamed, or change shape without notice; a dead mirror degrades to a counted
skip (`sources_failed`), never a crash, exactly like `backfill_congress`'s per-filer
fetch failures.

COVERAGE GAP (live-verified 2026-08-07, load-bearing for Task 6/7's honesty disclaimer):
Twitter permanently suspended @realDonaldTrump on 08-Jan-2021 (last tweet in the mirror:
2021-01-08); the Truth Social archive's earliest post is 2022-02-14. Roughly 13 months
(01/2021-02/2022) have NO statement coverage in either source -- not because nothing was
said, but because the platform ban silenced the one channel and the successor archive
only starts later. `backfill_statements` surfaces this as `twitter_date_max` /
`truth_social_date_min` in its returned counts so Task 7 can report the gap as a number,
not a footnote.

--- VERIFIED LAYOUT 1/2: MarkHershey/CompleteTrumpTweetsArchive (live download, both
files, 2026-08-07) -----------------------------------------------------------------
Two CSVs, no overlap: `realDonaldTrump_bf_office.csv` (04-May-2009 .. 19-Jan-2017,
31,249 rows) and `realDonaldTrump_in_office.csv` (20-Jan-2017 .. 08-Jan-2021, 23,075
rows) -- both fetched, both feed 2009-> per the plan's title.

Header is LITERALLY `ID, Time, Tweet URL, Tweet Text` -- comma+SPACE, not a plain comma,
and NOT RFC 4180 CSV for the last column. Surprises vs. the obvious reading:
  * `ID` is NOT a per-tweet id -- every single row repeats the constant handle
    "@realDonaldTrump". The real per-post id lives at the tail of `Tweet URL`
    (".../status/<digits>"), extracted here via regex.
  * `Tweet Text` LOOKS quoted ("...") but is not csv-module quoting: the field starts
    with a SPACE before the quote character, and Python's csv module (and every other
    RFC-4180 reader) only engages quote parsing when the quote is the field's very
    FIRST character. So a tweet containing an internal comma parses as MORE than 4
    comma-separated segments under `csv.reader` -- verified on the full 54,324-row
    corpus: 0 rows have exactly 4 comma-delimited segments once any tweet contains a
    comma (32%+ do). The robust parse is therefore a plain `str.split(", ", 3)`
    (maxsplit 3) per raw line: confirmed to split every one of the 54,324 real rows
    into exactly 4 parts with zero exceptions, followed by manually stripping the
    outer literal quote characters from the 4th part. Zero `""`-escaped internal
    quotes were found in either file, so no unescaping is needed.
  * `Time` has no timezone marker ("2009-05-04 13:54") -- treated as a naive local
    timestamp; same undocumented-timezone honesty limit as every other source in this
    repo lacking one.
  * No embedded newlines were found inside any tweet in either file (every one of the
    54,324 raw lines starts with the literal handle) -- so plain line-based splitting
    never needs to reassemble a multi-line record.
  * The raw text carries mojibake for non-ASCII punctuation (curly quotes/em-dashes
    show up as multi-codepoint UTF-8-in-Latin-1 garbage, e.g. "â€")
    from an upstream mis-decode. Left as-is -- it never touches the ASCII direction
    verbs or ticker letters the classifier keys on, and re-decoding it is out of
    scope here.

--- VERIFIED LAYOUT 2/2: stiles/trump-truth-social-archive `data/truth_archive.csv`
(live download, 2026-08-07, 29,469 rows) --------------------------------------------
Proper, RFC-compliant CSV (verified: `csv.reader` parses all 29,469 real rows with
zero column-count mismatches) -- unlike the Twitter archive above, no custom parsing
is needed. Columns: `id, created_at, content, url, media, replies_count, reblogs_count,
favourites_count`. `created_at` is ISO-8601 UTC with milliseconds
("2026-05-02T23:12:54.339Z"). `content` is EMPTY on image/video-only posts (`media`
holds the asset URL instead) -- verified 17.2% of the live file -- a real, expected
shape (counted as `no_text`), not a defect.

--- Reuse of voices.classify_mention (STRICT mode), and the MEASURED full-corpus yield --
`events_from_statement_rows` builds one `voices.Mention` per statement (speaker=person,
title=the statement text) and classifies it like a news headline, but with
`classify_mention(..., strict=True)`: the person's name (or an alias, or --
automatically, via `voices._name_in_title` -- their bare surname when longer than 3
chars) must appear BEFORE a closed-list direction phrase ("buys", "sells", "bullish
on", ...), and `resolve_ticker` must resolve to exactly one universe company via the
literal FULL-NAME-as-substring match ONLY (`voices.resolve_ticker`'s `strict`
docstring) -- the single-token-name, distinguishing-first-word and raw-caps-token
channels are all disabled here. A retweet/quote ("RT @"/"RT:" prefix) is never the
person's own statement and is filtered before classification; an exact-text repeat
within the batch (mirror-side duplication, mostly self-RTs) is deduped, first kept.

MEASURED, 2026-08-07, full real corpus (both Twitter files + the Truth Social archive,
`data/universe_combined.csv`, 7,499 companies) run through this exact pipeline:
78,728 total parsed statement rows (media-only Truth Social posts already excluded as
`no_text`) -> 14,019 retweets filtered -> 1,554 exact-text duplicates filtered ->
63,023 rows with no resolvable name+direction-phrase combination at all -> 132
candidate rows -> after full strict ticker resolution: **10 raw "events"**.

A manual spot-check of ALL 10 survivors (not a sample) found ZERO genuine investment
calls -- the honest yield of this entire 2009-2026 corpus, under strict + RT-filter +
dedupe, is effectively **ZERO**, matching the plan's own "expect ~0; that is a valid
result." Two residual false-positive classes explain the 10, both OUTSIDE the approved
fix package's scope (named here, not silently patched):
  * 9 of 10 resolve to ticker M (Macy's Inc): every one is about Trump-BRANDED
    MERCHANDISE (ties, cologne) being sold AT the retailer Macy's ("Selling like
    hotcakes", "buys some DJT ties... at Macy's"), never a stock opinion about Macy's
    the company. The literal company name "Macy's" genuinely, unambiguously appears in
    the text -- the full-name channel is not wrong to match it -- but the CONTENT is a
    merchandising mention, not a directional call; several of these ALSO carry the
    direction verb from a QUOTED FAN's reply text embedded in Trump's own tweet
    ("' @KSofen: ... I bought one of your ties at Macy's ...'" -- @KSofen bought the
    tie, not Trump), the same "someone else's verb becomes a Trump call" failure mode
    named for the RT case, but via an unprefixed quote-in-single-quotes citation style
    (pre-official-retweet-era Twitter) the `_RETWEET_PREFIXES` check does not catch.
  * 1 of 10 resolves to ticker DB (Deutsche Bank AG): a Truth Social repost of CNN
    courtroom coverage where "Kise added" ("Chris Kise, [Trump's] attorney,
    ADDED [a further remark]" -- ordinary reporting-verb English) collides with
    BULLISH_PHRASES's "added" (short for "added to a position") -- a homograph, not a
    name/ticker resolution error.
Neither class is addressed by this module (would require either dropping brand-name
tickers that double as common retail venues, or a quote-citation detector, or removing
homograph-prone phrases from voices.py's SHARED closed list -- all out of this task's
approved scope). Task 6/7 should treat the "statement" class as n approx 0 for the
2009-2026 window and decide separately whether it is worth a manual-review gate before
ever publishing a base rate from it.
"""
from __future__ import annotations

import csv
import html
import io
import re
from collections.abc import Callable
from datetime import datetime

from equity_scout.constants import DEFAULT_UNIVERSE_PATH
from equity_scout.evidence.base import SOURCE_STATEMENT
from equity_scout.evidence.historical_storage import HistoricalEvent, record_historical_events
from equity_scout.evidence.voices import (
    BEARISH_PHRASES,
    BULLISH_PHRASES,
    KIND_CALL,
    Mention,
    _name_in_title,
    _slug,
    classify_mention,
)
from equity_scout.universe import load_universe

DEFAULT_PERSON = "Donald Trump"
# No extra aliases are needed for this person: `voices._name_in_title` already adds
# the bare surname ("Trump") as a match candidate whenever it is longer than 3 chars,
# which alone covers every third-person self-reference in both archives
# ("Donald Trump ...", "...Donald J. Trump", "President Trump ..."). Kept as an empty
# list (matching several PERSONS entries in voices.py) rather than invented aliases.
DEFAULT_ALIASES: list[str] = []

# Best-effort community mirrors (verified live 2026-08-07) -- see module docstring for
# the exact column layout of each. Neither is an official Twitter/Truth Social export;
# either can go dark or change shape without notice.
TWITTER_ARCHIVE_CSV_URLS = (
    "https://raw.githubusercontent.com/MarkHershey/CompleteTrumpTweetsArchive"
    "/master/data/realDonaldTrump_bf_office.csv",
    "https://raw.githubusercontent.com/MarkHershey/CompleteTrumpTweetsArchive"
    "/master/data/realDonaldTrump_in_office.csv",
)
TRUTH_SOCIAL_ARCHIVE_CSV_URL = (
    "https://raw.githubusercontent.com/stiles/trump-truth-social-archive"
    "/main/data/truth_archive.csv"
)

_TWEET_URL_ID_RE = re.compile(r"/status/(\d+)\s*$")

# Every row lands in exactly one of these buckets except "kept", which is the OVERLAY
# convenience sum calls+bearish_calls (same overlay-outside-the-partition convention
# as backfill_form4.py's "bad_shares"): rows == calls + bearish_calls + context +
# unclassified + malformed + retweets + duplicate_text.
_PARTITION_KEYS = (
    "rows", "calls", "bearish_calls", "context", "unclassified", "malformed",
    "retweets", "duplicate_text",
)
_OVERLAY_COUNT_KEYS = ("kept",)

# A retweet/repost is NOT the person's own statement -- SOURCE_STATEMENT's whole
# contract is "this person said this", and an RT attributes someone ELSE's words
# (live P2a fabrication: an RT of a third party's NYT-bullish tweet became a
# Trump-bullish-on-NYT call). Checked on the LSTRIPPED text so a leading blank/quote
# character never defeats the prefix match.
_RETWEET_PREFIXES = ("RT @", "RT:")


def _http_get_default(url: str) -> str:
    import httpx

    response = httpx.get(
        url, timeout=60.0, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (equity-scout private research)"},
    )
    response.raise_for_status()
    return response.text


def _parse_twitter_timestamp(value: str) -> str | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").isoformat()
    except ValueError:
        return None


_TWITTER_EXPECTED_HEADER = "ID, Time, Tweet URL, Tweet Text"


def _rows_from_twitter_csv(csv_text: str) -> tuple[list[dict], dict]:
    """MarkHershey/CompleteTrumpTweetsArchive's CSV -> normalized statement rows.

    See the module docstring's "VERIFIED LAYOUT 1/2" block for why this is a plain
    line-based `split(", ", 3)` rather than `csv.reader`/`csv.DictReader`: the source
    is not RFC-4180 CSV for its last column, and a real csv reader mis-splits any
    tweet containing an internal comma.

    Unlike `_rows_from_truth_social_csv`'s named-column check, this format is
    POSITIONAL, not name-keyed -- so the only loud guard available against schema
    drift (a reordered/renamed column) is the literal header line itself. Raises
    ValueError when it does not match exactly: a silently reordered header would
    otherwise parse "successfully" into wrong fields (e.g. a swapped Time/URL) rather
    than failing, which is worse than a crash.

    Splits on plain `"\\n"` (+ manual `\\r` stripping) rather than `str.splitlines()`:
    the latter also breaks on Unicode line-separator characters (U+2028/U+2029/...),
    any of which can legitimately appear INSIDE a tweet's text -- `splitlines()` would
    silently truncate such a tweet at the separator instead of treating it as content.
    """
    counts = {"malformed": 0, "no_text": 0}
    rows: list[dict] = []
    lines = csv_text.lstrip("\ufeff").split("\n")
    header = lines[0].rstrip("\r").strip() if lines else ""
    if header != _TWITTER_EXPECTED_HEADER:
        raise ValueError(f"unexpected Twitter archive header: {header!r}")
    for raw_line in lines[1:]:  # skip header
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        parts = line.split(", ", 3)
        if len(parts) != 4:
            counts["malformed"] += 1
            continue
        _handle, time_str, url, quoted_text = parts
        match = _TWEET_URL_ID_RE.search(url.strip())
        text = quoted_text.strip()
        if text.startswith('"') and text.endswith('"') and len(text) >= 2:
            text = text[1:-1]
        published = _parse_twitter_timestamp(time_str.strip())
        if match is None or published is None:
            counts["malformed"] += 1
            continue
        if not text:
            counts["no_text"] += 1
            continue
        rows.append(
            {
                "platform": "twitter",
                "post_id": match.group(1),
                "text": text,
                "published": published,
            }
        )
    return rows, counts


_TRUTH_SOCIAL_REQUIRED_COLUMNS = ("id", "created_at", "content")


def _rows_from_truth_social_csv(csv_text: str) -> tuple[list[dict], dict]:
    """stiles/trump-truth-social-archive's `data/truth_archive.csv` -> normalized
    statement rows. Proper RFC-4180 CSV (see module docstring) -- `csv.DictReader`
    alone is enough, unlike the Twitter archive above.

    Raises ValueError when a column this module READS is missing -- schema drift on
    the live mirror must fail loudly, never silently produce a quiet zero-row run
    (same convention as backfill_form4.py's `_REQUIRED_COLUMNS` guard).

    `content` is HTML-escaped (Mastodon-API-style, e.g. "Tariffs &amp; Trade") --
    `html.unescape`d here, before the text ever reaches `classify_mention`, so a
    literal "&amp;" never breaks phrase adjacency or a company-name match.
    """
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    missing = [
        column
        for column in _TRUTH_SOCIAL_REQUIRED_COLUMNS
        if column not in (reader.fieldnames or ())
    ]
    if missing:
        raise ValueError(f"truth_archive.csv is missing read column(s): {', '.join(missing)}")

    counts = {"malformed": 0, "no_text": 0}
    rows: list[dict] = []
    for row in reader:
        if not isinstance(row, dict):
            counts["malformed"] += 1
            continue
        post_id = row.get("id")
        published = row.get("created_at")
        text = row.get("content")
        if not post_id or not published:
            counts["malformed"] += 1
            continue
        if not text or not text.strip():
            # ~17% of the live archive (verified 2026-08-07): an image/video post
            # with no caption -- a real shape, not a defect.
            counts["no_text"] += 1
            continue
        rows.append(
            {
                "platform": "truth_social",
                "post_id": str(post_id),
                "text": html.unescape(text),
                "published": published,
            }
        )
    return rows, counts


def _matched_phrase(text_lower: str, name_pos: int, direction: str) -> str:
    """Which closed-list phrase decided the classification. `classify_mention` itself
    only returns the direction, not the literal phrase (details need it per the plan) --
    this mirrors `voices._direction_after`'s own earliest-occurrence tie-break exactly,
    over the same (unmasked) `text_lower` classify_mention used internally, so the
    phrase reported here is provably the one that fired."""
    phrases = BULLISH_PHRASES if direction == "bullish" else BEARISH_PHRASES
    hits = [
        (text_lower.find(phrase, name_pos), phrase)
        for phrase in phrases
        if text_lower.find(phrase, name_pos) >= 0
    ]
    return min(hits)[1]


def events_from_statement_rows(
    rows: list[dict],
    universe: list[tuple[str, str]],
    aliases: list[str],
    *,
    person: str = DEFAULT_PERSON,
) -> tuple[list[HistoricalEvent], dict]:
    """Normalized statement rows -> `HistoricalEvent`s (bullish/bearish only) + a
    complete partition of skip counters.

    Each row is run through `voices.classify_mention` in STRICT mode (only the
    literal full-company-name match resolves a ticker -- see `voices.resolve_ticker`'s
    docstring): only unambiguous (ticker, direction) hits are kept (KIND_CONTEXT and a
    `None` classification are both counted, never stored -- a context mention has no
    direction to resolve, and "unclassified" folds together every reason
    classify_mention itself refuses to disclose: no name in the text, no resolvable
    ticker, or an ambiguous one). A retweet/repost (`text` starting with "RT @" or
    "RT:") is never the person's OWN statement and is counted (`retweets`) before ever
    reaching the classifier. An exact-text repeat within this batch (mirror-side
    duplication, mostly self-RTs) is counted (`duplicate_text`) and skipped, first
    occurrence kept. T0 is the DATE part of the post timestamp (`published[:10]`,
    consistent with the plain-date t0 the congress/form4 backfills use) -- the full
    timestamp is preserved in `details["published"]`, never dropped. event_key is
    `f"{person_slug}-{post_id}"` per plan Task 4 -- collision risk across the two
    platforms' independent id spaces is negligible (both are large, effectively
    disjoint integer ranges) and `details["platform"]` still records which archive a
    row came from for any future audit.
    """
    counts = dict.fromkeys(_PARTITION_KEYS + _OVERLAY_COUNT_KEYS, 0)
    person_slug = _slug(person)
    seen_texts: set[str] = set()
    events: list[HistoricalEvent] = []
    for row in rows:
        counts["rows"] += 1
        if not isinstance(row, dict):
            counts["malformed"] += 1
            continue
        platform = row.get("platform")
        post_id = row.get("post_id")
        text = row.get("text")
        published = row.get("published")
        if (
            not isinstance(platform, str) or not platform.strip()
            or not post_id
            or not isinstance(text, str) or not text.strip()
            or not isinstance(published, str) or not published.strip()
        ):
            counts["malformed"] += 1
            continue
        if text.lstrip().startswith(_RETWEET_PREFIXES):
            counts["retweets"] += 1
            continue
        if text in seen_texts:
            counts["duplicate_text"] += 1
            continue
        seen_texts.add(text)

        mention = Mention(speaker=person, title=text, feed=platform, published=published)
        classified = classify_mention(mention, universe, aliases, strict=True)
        if classified is None:
            counts["unclassified"] += 1
            continue
        kind, ticker, direction = classified
        if direction is None:  # KIND_CONTEXT: has a ticker, no direction to resolve
            counts["context"] += 1
            continue

        text_lower = text.lower()
        name_pos = _name_in_title(person, aliases, text_lower)
        phrase = _matched_phrase(text_lower, name_pos, direction)
        counts["calls" if kind == KIND_CALL else "bearish_calls"] += 1
        counts["kept"] += 1
        events.append(
            HistoricalEvent(
                source=SOURCE_STATEMENT,
                person=person,
                ticker=ticker,
                event_key=f"{person_slug}-{post_id}",
                t0=published[:10],
                details={
                    "platform": platform,
                    "direction": direction,
                    "matched_phrase": phrase,
                    "text": text,
                    "published": published,
                },
            )
        )
    return events, counts


def backfill_statements(
    db_path: str,
    *,
    now: str,
    http_get: Callable[[str], str] | None = None,
    universe: list[tuple[str, str]] | None = None,
) -> dict:
    """Fetch both archive CSVs, classify every statement, record new events.

    Every source is fetched independently: a dead/renamed mirror raises inside its own
    fetch and is counted via `sources_failed` (never aborting the other two, same
    per-item-degrades convention as `backfill_congress`'s per-filer loop). A source that
    DOES fetch but whose content has drifted out of the expected shape (renamed/
    reordered column) raises ValueError from the parser and is counted separately via
    `sources_parse_failed` -- distinct from `sources_failed` because Task 7 needs to
    tell "mirror is offline" apart from "mirror is up but changed shape". All three
    sources failing (either way) still returns a structurally complete, all-zero counts
    dict (`rows == 0`, `events_new == 0`) rather than raising -- loud via the returned
    counts, never a crash and never mistaken for a quiet no-op because the failure
    counters are right there next to it. Every such failure also appends a
    human-readable `f"{url}: {err}"` line to `counts["source_errors"]` (mirrors
    `backfill_form4._fetch_quarter_zip`'s detail convention) -- a bare integer cannot
    tell a 404 apart from a schema-drift ValueError.

    Real yield is expected to be LOW-to-ZERO -- see the module docstring's measured
    full-corpus numbers, not the collector's own summary counts.

    `universe` defaults to the full tracked universe (`data/universe_combined.csv`,
    same file `run_evidence.py` loads for the live voices collector) when not
    supplied -- overridable for tests/subset runs.
    """
    get = http_get if http_get is not None else _http_get_default
    if universe is None:
        universe = [
            (instrument.ticker, instrument.name)
            for instrument in load_universe(DEFAULT_UNIVERSE_PATH)
        ]

    counts: dict = {
        "sources_fetched": 0, "sources_failed": 0, "sources_parse_failed": 0,
        "source_errors": [],
        "twitter_rows": 0, "truth_social_rows": 0,
        # CSV-parse-time skip buckets, kept separate per platform and distinct from
        # the classify-time "malformed"/"unclassified"/etc. buckets below -- these two
        # stages count different failure modes (a broken CSV line vs. a well-formed
        # row the classifier can't use) and must never be summed into one number.
        "twitter_malformed": 0, "twitter_no_text": 0,
        "truth_social_malformed": 0, "truth_social_no_text": 0,
        "twitter_date_min": None, "twitter_date_max": None,
        "truth_social_date_min": None, "truth_social_date_max": None,
        "events_new": 0, "events_seen": 0,
        **dict.fromkeys(_PARTITION_KEYS + _OVERLAY_COUNT_KEYS, 0),
    }

    all_rows: list[dict] = []
    platform_dates: dict[str, list[str]] = {"twitter": [], "truth_social": []}
    sources: tuple[tuple[str, str], ...] = (
        ("twitter", TWITTER_ARCHIVE_CSV_URLS[0]),
        ("twitter", TWITTER_ARCHIVE_CSV_URLS[1]),
        ("truth_social", TRUTH_SOCIAL_ARCHIVE_CSV_URL),
    )
    for platform, url in sources:
        try:
            csv_text = get(url)
        except Exception as err:  # noqa: BLE001 -- a dead/renamed mirror is a status, not a crash
            counts["sources_failed"] += 1
            counts["source_errors"].append(f"{url}: {err}")
            continue
        counts["sources_fetched"] += 1
        try:
            if platform == "twitter":
                rows, parse_counts = _rows_from_twitter_csv(csv_text)
            else:
                rows, parse_counts = _rows_from_truth_social_csv(csv_text)
        except ValueError as err:
            # Fetched fine, but the content no longer matches the verified layout
            # (renamed/reordered column) -- counted, never a crash mid-run.
            counts["sources_parse_failed"] += 1
            counts["source_errors"].append(f"{url}: {err}")
            continue
        counts[f"{platform}_rows"] += len(rows)
        counts[f"{platform}_malformed"] += parse_counts["malformed"]
        counts[f"{platform}_no_text"] += parse_counts["no_text"]
        platform_dates[platform].extend(row["published"] for row in rows)
        all_rows.extend(rows)

    for platform in ("twitter", "truth_social"):
        dates = platform_dates[platform]
        if dates:
            counts[f"{platform}_date_min"] = min(dates)
            counts[f"{platform}_date_max"] = max(dates)

    events, class_counts = events_from_statement_rows(
        all_rows, universe, DEFAULT_ALIASES, person=DEFAULT_PERSON
    )
    for key in _PARTITION_KEYS + _OVERLAY_COUNT_KEYS:
        counts[key] += class_counts[key]
    counts["events_seen"] = len(events)
    counts["events_new"] = len(record_historical_events(db_path, events, now=now))
    return counts
