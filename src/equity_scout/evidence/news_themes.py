"""Cross-source news-theme radar: what is the market talking about, and which
watchlist stocks does that touch?

Broad (non-ticker) headlines come from Google News RSS + MarketWatch + the Fed press
feed (free; Google's feed is undocumented and may break — every feed fails
independently and is reported per feed, never silently). Theme detection is
DETERMINISTIC counting: a theme is a token bigram (fallback unigram) that appears in
>= min_hits headlines from >= min_sources distinct feeds — no LLM anywhere in this
module, so a theme can always be traced back to the exact headlines that caused it.
The same wire story often lands in two feeds under a different outlet suffix; it is
deduped by normalized-title hash (mirrors voices.dedupe_mentions) BEFORE counting, so
one syndicated article can never masquerade as two independent source confirmations.
A theme only becomes ticker evidence when that ticker's OWN recent headlines contain
the theme phrase — "the theme touches this stock" stays a observable text fact, and
is context, never a forecast (by the time a theme is in the news, it is in the price).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from equity_scout.evidence.base import (
    SOURCE_NEWS_THEME,
    STATUS_FETCH_FAILED,
    STATUS_OK,
    CollectorResult,
    EvidenceEvent,
    title_hash,
)

FEEDS: dict[str, str] = {
    "google-news": (
        "https://news.google.com/rss/search"
        "?q=stock%20market%20OR%20economy%20OR%20industry%20when:2d"
        "&hl=en-US&gl=US&ceid=US:en"
    ),
    "marketwatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "fed": "https://www.federalreserve.gov/feeds/press_all.xml",
}

MIN_HITS = 3
MIN_SOURCES = 2
MAX_THEMES = 5

# Finance-headline boilerplate + common English filler. Heuristic by nature: the goal
# is that surviving bigrams read as CONTENT ("energy prices", "rate cut"), not syntax.
_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have how in is it its of on or that the
    this to was what when where which who will with you your not no over under after
    before amid says said new report week day today year years month stocks stock market
    markets share shares trading trade investors investor wall street dow nasdaq rally
    close open high low points percent billion million company companies inc corp us
    why how business best top big could should would may might more most next first
    last still just even back live watch here look latest breaking update analysis""".split()
)


@dataclass(frozen=True)
class Headline:
    title: str
    source: str  # feed name


@dataclass(frozen=True)
class Theme:
    keyword: str  # human-readable phrase, e.g. "energy prices"
    hits: int
    sources: list[str]
    example_titles: list[str]


def _http_get_default(url: str) -> str:
    import httpx

    response = httpx.get(
        url, timeout=30.0, follow_redirects=True,
        # Google News answers plain clients; a UA avoids over-eager bot filters.
        headers={"User-Agent": "Mozilla/5.0 (equity-scout private research)"},
    )
    response.raise_for_status()
    return response.text


def parse_feed(xml_text: str, source: str) -> list[Headline]:
    """RSS 2.0 <item><title> and Atom <entry><title>, namespace-tolerant."""
    root = ET.fromstring(xml_text)

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    headlines: list[Headline] = []
    for element in root.iter():
        if local(element.tag) not in {"item", "entry"}:
            continue
        for child in element:
            title = (child.text or "").strip() if local(child.tag) == "title" else ""
            if title:
                headlines.append(Headline(title=title, source=source))
                break
    return headlines


def fetch_headlines(
    http_get: Callable[[str], str] | None = None,
) -> tuple[list[Headline], dict[str, str]]:
    """All feeds, each failing independently; per-feed status for the detail line."""
    get = http_get if http_get is not None else _http_get_default
    headlines: list[Headline] = []
    feed_status: dict[str, str] = {}
    for source, url in FEEDS.items():
        try:
            parsed = parse_feed(get(url), source)
        except Exception as err:  # noqa: BLE001 — a broken feed is a status, not a crash
            feed_status[source] = f"failed: {err}"
            continue
        feed_status[source] = f"ok ({len(parsed)})"
        headlines.extend(parsed)
    return headlines, feed_status


def dedupe_headlines(headlines: list[Headline]) -> list[Headline]:
    """Same story syndicated across feeds collapses to one — otherwise a single wire
    article counted from N feeds inflates both the hit count and the distinct-source
    count MIN_HITS/MIN_SOURCES rely on (live finding 2026-07-15)."""
    seen: set[str] = set()
    unique: list[Headline] = []
    for headline in headlines:
        key = title_hash(headline.title)
        if key in seen:
            continue
        seen.add(key)
        unique.append(headline)
    return unique


def _tokens(title: str) -> list[str]:
    return [
        token
        for token in "".join(ch if ch.isalnum() else " " for ch in title.lower()).split()
        if token not in _STOPWORDS and len(token) > 2 and not token.isdigit()
    ]


def detect_themes(
    headlines: list[Headline],
    *,
    min_hits: int = MIN_HITS,
    min_sources: int = MIN_SOURCES,
    max_themes: int = MAX_THEMES,
) -> list[Theme]:
    """Bigrams first (more specific), then unigrams not already covered by a theme.

    A lone word is far noisier than a phrase ("bank" vs "energy prices"), so unigrams
    must clear TWICE the hit bar to qualify — the live 2026-07-07 smoke run surfaced
    "bank"/"business"-grade noise at the shared threshold.
    """
    bigram_seen: dict[str, list[Headline]] = {}
    unigram_seen: dict[str, list[Headline]] = {}
    for headline in dedupe_headlines(headlines):
        tokens = _tokens(headline.title)
        for phrase in {f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False)}:
            bigram_seen.setdefault(phrase, []).append(headline)
        for token in set(tokens):
            unigram_seen.setdefault(token, []).append(headline)

    def qualify(seen: dict[str, list[Headline]], required_hits: int) -> list[Theme]:
        themes = []
        for phrase, hits in seen.items():
            sources = sorted({h.source for h in hits})
            if len(hits) >= required_hits and len(sources) >= min_sources:
                themes.append(
                    Theme(
                        keyword=phrase,
                        hits=len(hits),
                        sources=sources,
                        example_titles=[h.title for h in hits[:3]],
                    )
                )
        return sorted(themes, key=lambda t: (-t.hits, t.keyword))

    themes = qualify(bigram_seen, min_hits)
    covered = {word for theme in themes for word in theme.keyword.split()}
    themes += [t for t in qualify(unigram_seen, min_hits * 2) if t.keyword not in covered]
    return themes[:max_themes]


def match_ticker_headlines(
    themes: list[Theme], ticker_headlines: dict[str, list[str]], *, now: str
) -> list[EvidenceEvent]:
    """A theme becomes evidence for a ticker only when the phrase occurs in that
    ticker's own headlines. Event keys rotate per ISO week, so a persistent theme
    re-logs at most weekly instead of flooding the ledger daily."""
    year, week, _ = datetime.fromisoformat(now).isocalendar()
    events: list[EvidenceEvent] = []
    for ticker, titles in ticker_headlines.items():
        normalized = [" ".join(_tokens(title)) for title in titles]
        for theme in themes:
            matched = next(
                (title for title, norm in zip(titles, normalized, strict=False)
                 if theme.keyword in norm),
                None,
            )
            if matched is None:
                continue
            events.append(
                EvidenceEvent(
                    source=SOURCE_NEWS_THEME,
                    ticker=ticker,
                    event_key=f"{theme.keyword.replace(' ', '-')}-{year}w{week:02d}",
                    event_date=now[:10],
                    details={
                        "theme": theme.keyword,
                        "hits": theme.hits,
                        "sources": theme.sources,
                        "matched_headline": matched,
                    },
                )
            )
    return events


def collect_news_themes(
    *,
    now: str,
    ticker_headlines: dict[str, list[str]],
    http_get: Callable[[str], str] | None = None,
) -> CollectorResult:
    headlines, feed_status = fetch_headlines(http_get)
    status_line = ", ".join(f"{name}: {state}" for name, state in feed_status.items())
    if not headlines:
        return CollectorResult(SOURCE_NEWS_THEME, STATUS_FETCH_FAILED, detail=status_line)
    themes = detect_themes(headlines)
    events = match_ticker_headlines(themes, ticker_headlines, now=now)
    detail = (
        f"{len(headlines)} headlines -> {len(themes)} themes "
        f"({', '.join(t.keyword for t in themes) or 'none'}) -> {len(events)} ticker "
        f"events; feeds: {status_line}"
    )
    return CollectorResult(SOURCE_NEWS_THEME, STATUS_OK, events=events, detail=detail)
