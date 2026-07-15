"""Deterministic beat/miss/guidance classifier for news headlines + 8-K item categories
(Strang B3).

Keyword/phrase matching only — no LLM anywhere in this module. Conservative by design:
a headline that matches more than one category (a genuine dual event, e.g. "beats
estimates but cuts guidance"), or whose match sits right after a negation ("fails to
beat estimates"), classifies as "unknown" rather than guessing a direction. 8-K
filings carry no free-text title at all (see edgar_8k.py's module docstring — the
submissions API never delivers one), so they only ever get a category derived from
their item codes, never a beat/miss direction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from equity_scout.evidence.base import SOURCE_8K, SOURCE_NEWS, EvidenceEvent, title_hash

EVENT_BEAT = "beat"
EVENT_MISS = "miss"
EVENT_GUIDANCE_UP = "guidance_up"
EVENT_GUIDANCE_DOWN = "guidance_down"
EVENT_UNKNOWN = "unknown"
EVENT_EARNINGS_FILED = "earnings_filed"
EVENT_OTHER_8K = "other_8k"

# The result noun must be an unambiguous earnings term. `street`/`consensus` were
# dropped as bare alternatives: "Top Wall Street ..." is one of the most common finance
# headline phrases and is not an earnings beat (review finding B3) — a missed genuine
# beat is acceptable, a wrongly-directed signal is not.
_RESULT_NOUN = r"(estimates?|expectations?|forecasts?)"
_BEAT_PATTERNS = [
    rf"\bbeats?\b.{{0,20}}\b{_RESULT_NOUN}\b",
    rf"\btops?\b.{{0,20}}\b{_RESULT_NOUN}\b",
    rf"\bsurpass(?:es|ed)?\b.{{0,20}}\b{_RESULT_NOUN}\b",
    rf"\bexceeds?\b.{{0,20}}\b{_RESULT_NOUN}\b",
]
_MISS_PATTERNS = [
    rf"\bmiss(?:es|ed)?\b.{{0,20}}\b{_RESULT_NOUN}\b",
    r"\bfalls?\s+short\b",
    r"\bfell\s+short\b",
]
_GUIDANCE_UP_PATTERNS = [
    r"\b(raises?|lifts?|boosts?|hikes?)\b.{0,20}\b(guidance|outlook|forecast)\b",
]
_GUIDANCE_DOWN_PATTERNS = [
    r"\b(cuts?|lowers?|slashes?|trims?|reduces?)\b.{0,20}\b(guidance|outlook|forecast)\b",
]

# A negation or hedge right before a matched phrase voids it ("fails to beat
# estimates", "will not beat estimates", "unlikely to beat estimates" are not beats) —
# conservative rule: drop the match rather than guess the opposite category.
_NEGATION_RE = re.compile(
    r"\b("
    r"fails?|failed|unable|unlikely|"
    r"will\s+not|won'?t|would\s+not|wouldn'?t|"
    r"does\s*n[o']?t|did\s*n[o']?t|do\s*n[o']?t|is\s*n[o']?t|are\s*n[o']?t|"
    r"can'?t|cannot|"
    r"not\s+expected|not\s+likely|no\s+longer"
    r")\b(\s+to)?\s*$"
)


def _matches(text: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            prefix = text[max(0, match.start() - 25) : match.start()]
            if _NEGATION_RE.search(prefix):
                continue
            return True
    return False


def classify_headline(title: str) -> str:
    """Map one news headline to beat/miss/guidance_up/guidance_down/unknown.

    Conservative: no match, a negated match, or matches in more than one category all
    fall back to "unknown" — never a guess (honesty over recall).
    """
    text = (title or "").lower()
    hits = {
        EVENT_BEAT: _matches(text, _BEAT_PATTERNS),
        EVENT_MISS: _matches(text, _MISS_PATTERNS),
        EVENT_GUIDANCE_UP: _matches(text, _GUIDANCE_UP_PATTERNS),
        EVENT_GUIDANCE_DOWN: _matches(text, _GUIDANCE_DOWN_PATTERNS),
    }
    matched = [label for label, hit in hits.items() if hit]
    return matched[0] if len(matched) == 1 else EVENT_UNKNOWN


def classify_8k_items(items: list[str]) -> str:
    """Category only, never a direction — see module docstring."""
    return EVENT_EARNINGS_FILED if "2.02" in (items or []) else EVENT_OTHER_8K


@dataclass(frozen=True)
class ClassifiedEvent:
    ticker: str
    event_type: str
    source: str  # SOURCE_NEWS or SOURCE_8K
    published_at: str | None  # from the source; honestly NULL when the source has none
    detail: str | None  # the headline text, or a short 8-K item description
    event_key: str  # idempotency key for event_storage.save_classified_events


def build_classified_events(
    *, news_by_ticker: dict[str, list[dict]], eightk_events: list[EvidenceEvent]
) -> list[ClassifiedEvent]:
    """Pure glue: watchlist news headlines + already-collected 8-K events -> the flat
    list this Strang stores. No I/O, no wall clock — seen_at is injected later, at
    storage time (event_storage.save_classified_events)."""
    events: list[ClassifiedEvent] = []
    for ticker, headlines in news_by_ticker.items():
        for headline in headlines:
            title = headline.get("title") or ""
            if not title:
                continue
            events.append(
                ClassifiedEvent(
                    ticker=ticker.upper(),
                    event_type=classify_headline(title),
                    source=SOURCE_NEWS,
                    published_at=headline.get("published") or None,
                    detail=title,
                    event_key=f"news-{ticker.upper()}-{title_hash(title)}",
                )
            )
    for event in eightk_events:
        items = event.details.get("items") or []
        events.append(
            ClassifiedEvent(
                ticker=event.ticker.upper(),
                event_type=classify_8k_items(items),
                source=SOURCE_8K,
                published_at=event.details.get("published_at") or None,
                detail=f"8-K items: {', '.join(items)}" if items else None,
                event_key=f"{SOURCE_8K}-{event.event_key}",
            )
        )
    return events
