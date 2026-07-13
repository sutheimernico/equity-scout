"""Voices: what tracked famous investors SAY in public, as a fifth evidence source.

Free person-query news feeds (Google News RSS + Bing News RSS, both live-verified
2026-07-13) are MENTIONS feeds, not statements feeds: most hits are listicles and
encyclopedia-grade mentions, not quotes. The honest boundary is therefore drawn
deterministically, with no LLM anywhere in this module:

- A headline becomes a **measurable call** only when (1) the speaker's name appears in
  the title BEFORE (2) a direction phrase from a closed list, and (3) exactly one
  universe company/ticker resolves from the title — ambiguity is a non-match, never a
  guess. Bullish calls (`kind="call"`) enter the predict-then-resolve ledger and the
  speaker's person track record. Bearish calls (`kind="call_bearish"`) are stored,
  displayed and alerted, but stay OUT of the ledger and track records until signed
  (short-direction) resolution exists — resolving a short call as a long would invert
  its meaning into a fabricated statistic.
- Everything else with a resolvable ticker is a **context mention** (`kind="context"`):
  shown on pitches, never ledgered, never a track-record call.
- Mentions without a resolvable ticker are skipped — there is no ticker to attach them
  to, and inventing one would be a guess.

The closed verb list needs real-world tuning: read the first weeks of voice calls
manually before trusting voice person scores (see plan P1, honest limits).
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from equity_scout.evidence.base import (
    SOURCE_VOICE,
    STATUS_FETCH_FAILED,
    STATUS_OK,
    CollectorResult,
    EvidenceEvent,
)
from equity_scout.evidence.edgar import _normalize as _normalize_issuer

# Person -> title aliases (the query always uses the canonical name; aliases only
# widen TITLE attribution). Managers of the 8 funds edgar.TRACKED_FUNDS follows —
# extending or vetoing this list is Nico's call (plan P1, Needs Nico).
PERSONS: dict[str, list[str]] = {
    "Warren Buffett": [],
    "Michael Burry": [],
    "Bill Ackman": [],
    "David Tepper": [],
    "Stanley Druckenmiller": [],
    "Daniel Loeb": ["Dan Loeb"],
    "Seth Klarman": [],
    "Li Lu": [],
}

KIND_CALL = "call"  # bullish, measurable -> ledger + person track record
KIND_CALL_BEARISH = "call_bearish"  # measurable but short-direction -> display/alert only
KIND_CONTEXT = "context"  # mention with a ticker, no direction -> display only

# Closed direction lists. A phrase must appear AFTER the speaker's name in the title
# (crude subject heuristic) to count — "analyst bearish on TSLA, unlike Burry" must
# not become a Burry call.
BULLISH_PHRASES = (
    "buys", "buying", "bought", "adds", "added", "bullish on", "sees upside",
    "raises stake", "increases stake", "goes long", "long on", "doubles down on",
)
BEARISH_PHRASES = (
    "shorts", "shorting", "short position", "bearish on", "bets against",
    "puts against", "dumps", "sells", "selling", "sold", "exits", "cuts stake",
    "trims stake", "warns on",
)

MAX_HEADLINE_AGE_DAYS = 3  # feeds return archive hits; a stale mention is not news

# All-caps title tokens that look like tickers but are almost always English words or
# finance boilerplate. Universe tickers colliding with real words ("ALL", "SO") lose
# symbol matching and must match via company name instead — an honest miss, not a guess.
_SYMBOL_STOPWORDS = frozenset(
    "A I AI AN ALL ARE BE BY CEO DO ETF FOR GO IN IT ITS NEW NOW ON OR OUT Q SEE SO "
    "TV UK US VS".split()
)

_FEED_URLS: dict[str, str] = {
    "google-news": (
        "https://news.google.com/rss/search?q=%22{query}%22%20when:2d"
        "&hl=en-US&gl=US&ceid=US:en"
    ),
    "bing-news": "https://www.bing.com/news/search?q=%22{query}%22&format=RSS&mkt=en-US",
}


@dataclass(frozen=True)
class Mention:
    speaker: str
    title: str
    feed: str
    published: str  # ISO date


def _http_get_default(url: str) -> str:
    import httpx

    response = httpx.get(
        url, timeout=30.0, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (equity-scout private research)"},
    )
    response.raise_for_status()
    return response.text


def parse_feed_dated(xml_text: str) -> list[tuple[str, str]]:
    """(title, ISO date) pairs; items without a parseable pubDate get today-unknown ''."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    items: list[tuple[str, str]] = []
    for element in root.iter():
        if local(element.tag) not in {"item", "entry"}:
            continue
        title, published = "", ""
        for child in element:
            name = local(child.tag)
            text = (child.text or "").strip()
            if name == "title" and text:
                title = text
            elif name in {"pubDate", "published", "updated"} and text:
                try:
                    published = parsedate_to_datetime(text).date().isoformat()
                except (TypeError, ValueError):
                    try:
                        published = datetime.fromisoformat(text).date().isoformat()
                    except ValueError:
                        published = ""
        if title:
            items.append((title, published))
    return items


def _title_hash(title: str) -> str:
    # Google News suffixes titles with " - <outlet>"; strip it so the same story
    # syndicated to two outlets hashes identically (live finding 2026-07-13).
    story = title.rsplit(" - ", 1)[0] if " - " in title else title
    normalized = " ".join(
        "".join(ch if ch.isalnum() else " " for ch in story.lower()).split()
    )
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def dedupe_mentions(mentions: list[Mention]) -> list[Mention]:
    """Same story syndicated across feeds/outlets collapses via normalized-title hash
    (feed GUIDs differ per outlet and are useless for this)."""
    seen: set[tuple[str, str]] = set()
    unique: list[Mention] = []
    for mention in mentions:
        key = (mention.speaker, _title_hash(mention.title))
        if key in seen:
            continue
        seen.add(key)
        unique.append(mention)
    return unique


def _name_in_title(speaker: str, aliases: list[str], title_lower: str) -> int:
    """Position of the speaker's name (any alias, else last name) in the title, -1 if
    absent. The QUERY guarantees the article mentions the person; the TITLE must too,
    or attribution on the displayed line would be unverifiable."""
    candidates = [speaker.lower(), *(a.lower() for a in aliases)]
    last_name = speaker.split()[-1].lower()
    if len(last_name) > 3:  # "Lu" alone would match inside random words
        candidates.append(last_name)
    positions = [title_lower.find(c) for c in candidates if title_lower.find(c) >= 0]
    return min(positions) if positions else -1


def _direction_after(title_lower: str, name_pos: int) -> tuple[str, int] | None:
    """(direction, position) of the earliest closed-list phrase AFTER the name."""
    hits: list[tuple[int, str]] = []
    for phrase in BULLISH_PHRASES:
        pos = title_lower.find(phrase, name_pos)
        if pos >= 0:
            hits.append((pos, "bullish"))
    for phrase in BEARISH_PHRASES:
        pos = title_lower.find(phrase, name_pos)
        if pos >= 0:
            hits.append((pos, "bearish"))
    if not hits:
        return None
    pos, direction = min(hits)
    return direction, pos


def resolve_ticker(title: str, universe: list[tuple[str, str]]) -> str | None:
    """Exactly one universe company per title, or None — ambiguity is a non-match.

    Two deterministic channels: (1) an all-caps token equal to a universe ticker
    (stopword-filtered), (2) the company's normalized name contained in the normalized
    title. Single-token company names additionally require a capitalized occurrence in
    the original title ("Target" the retailer vs "target prices").
    """
    tokens = ["".join(ch for ch in tok if ch.isalnum()) for tok in title.split()]
    caps_tokens = {
        tok for tok in tokens
        if tok.isupper() and 2 <= len(tok) <= 5 and tok not in _SYMBOL_STOPWORDS
    }
    normalized_title = " ".join(
        "".join(ch if ch.isalnum() else " " for ch in title.upper()).split()
    )
    padded_title = f" {normalized_title} "

    matched: set[str] = set()
    for ticker, name in universe:
        if ticker in caps_tokens:
            matched.add(ticker)
            continue
        norm_name = _normalize_issuer(name)
        if not norm_name or f" {norm_name} " not in padded_title:
            continue
        if " " not in norm_name:  # single-token name: demand a capitalized original
            if not any(tok.upper() == norm_name and tok[:1].isupper() for tok in tokens):
                continue
        matched.add(ticker)
    return matched.pop() if len(matched) == 1 else None


def classify_mention(
    mention: Mention, universe: list[tuple[str, str]], aliases: list[str]
) -> tuple[str, str, str | None] | None:
    """-> (kind, ticker, direction|None) or None when the mention is unusable
    (name not in title, or no unambiguous ticker)."""
    title_lower = mention.title.lower()
    name_pos = _name_in_title(mention.speaker, aliases, title_lower)
    if name_pos < 0:
        return None
    ticker = resolve_ticker(mention.title, universe)
    if ticker is None:
        return None
    directed = _direction_after(title_lower, name_pos)
    if directed is None:
        return KIND_CONTEXT, ticker, None
    direction, _ = directed
    kind = KIND_CALL if direction == "bullish" else KIND_CALL_BEARISH
    return kind, ticker, direction


def _slug(text: str) -> str:
    return "-".join(
        "".join(ch if ch.isalnum() else " " for ch in text.lower()).split()
    )


def collect_voices(
    *,
    now: str,
    universe: list[tuple[str, str]],
    persons: dict[str, list[str]] | None = None,
    http_get: Callable[[str], str] | None = None,
) -> CollectorResult:
    """Every (person, feed) fetch fails independently; a complete wipe-out degrades the
    source to fetch_failed. Event keys rotate per ISO week, so a syndicated story
    re-logs at most weekly."""
    persons = persons if persons is not None else PERSONS
    get = http_get if http_get is not None else _http_get_default
    now_dt = datetime.fromisoformat(now)
    year, week, _ = now_dt.isocalendar()
    oldest = (now_dt - timedelta(days=MAX_HEADLINE_AGE_DAYS)).date().isoformat()

    mentions: list[Mention] = []
    feed_status: dict[str, str] = {}
    for speaker in persons:
        for feed, url_template in _FEED_URLS.items():
            key = f"{feed}/{speaker.split()[-1]}"
            url = url_template.format(query=quote(speaker))
            try:
                items = parse_feed_dated(get(url))
            except Exception as err:  # noqa: BLE001 — a broken feed is a status, not a crash
                feed_status[key] = f"failed: {err}"
                continue
            fresh = [
                Mention(speaker=speaker, title=title, feed=feed, published=published)
                for title, published in items
                if published and published >= oldest
            ]
            feed_status[key] = f"ok ({len(fresh)}/{len(items)} fresh)"
            mentions.extend(fresh)

    status_line = ", ".join(f"{name}: {state}" for name, state in feed_status.items())
    if mentions == [] and all(state.startswith("failed") for state in feed_status.values()):
        return CollectorResult(SOURCE_VOICE, STATUS_FETCH_FAILED, detail=status_line)

    events: list[EvidenceEvent] = []
    counters = {"mentions": 0, "calls": 0, "bearish_calls": 0, "context": 0, "skipped": 0}
    for mention in dedupe_mentions(mentions):
        counters["mentions"] += 1
        classified = classify_mention(mention, universe, persons.get(mention.speaker, []))
        if classified is None:
            counters["skipped"] += 1
            continue
        kind, ticker, direction = classified
        counter_key = {
            KIND_CALL: "calls", KIND_CALL_BEARISH: "bearish_calls", KIND_CONTEXT: "context",
        }[kind]
        counters[counter_key] += 1
        key_kind = "mention" if kind == KIND_CONTEXT else direction
        details = {
            "speaker": mention.speaker,
            "kind": kind,
            "headline": mention.title,
            "feed": mention.feed,
            "published": mention.published,
        }
        if direction is not None:
            details["direction"] = direction
        events.append(
            EvidenceEvent(
                source=SOURCE_VOICE,
                ticker=ticker,
                event_key=f"{_slug(mention.speaker)}-{key_kind}-{year}w{week:02d}",
                event_date=mention.published,
                details=details,
            )
        )
    detail = (
        f"{counters['mentions']} mentions -> {counters['calls']} calls,"
        f" {counters['bearish_calls']} bearish calls, {counters['context']} context,"
        f" {counters['skipped']} skipped; feeds: {status_line}"
    )
    return CollectorResult(SOURCE_VOICE, STATUS_OK, events=events, detail=detail)
