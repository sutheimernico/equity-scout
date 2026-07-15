"""Shared evidence-collector contract.

Every external source (congress trades, 13F, news themes) returns a CollectorResult
instead of raising or returning a bare list: an empty `events` with status "ok" is a
real "nothing new", while "unconfigured" / "fetch_failed" / "parse_failed" carry an
explicit human-readable reason — a dead source must never be mistaken for a quiet one.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

SOURCE_CONGRESS = "congress"
SOURCE_13F = "thirteen_f"
SOURCE_NEWS_THEME = "news_theme"
SOURCE_INSIDER = "insider"
SOURCE_VOICE = "voice"
SOURCE_8K = "edgar_8k"

STATUS_OK = "ok"
STATUS_UNCONFIGURED = "unconfigured"
STATUS_FETCH_FAILED = "fetch_failed"
STATUS_PARSE_FAILED = "parse_failed"


@dataclass(frozen=True)
class EvidenceEvent:
    source: str
    ticker: str
    # Idempotency key within (source, ticker): re-collecting the same underlying fact
    # (same politician+date+direction, same fund+quarter, same theme+day) is a no-op.
    event_key: str
    event_date: str  # ISO date of the underlying fact (transaction/filing/detection day)
    details: dict  # JSON-serializable extras for display, alerts and the ledger


@dataclass(frozen=True)
class CollectorResult:
    source: str
    status: str
    events: list[EvidenceEvent] = field(default_factory=list)
    detail: str = ""  # skip/error reason; empty when status is "ok"


def title_hash(title: str) -> str:
    """Normalized-title hash for syndication dedupe (voices mentions, news-theme
    headlines). Google News suffixes titles with " - <outlet>"; strip it so the same
    story syndicated to two outlets/feeds hashes identically (live finding 2026-07-13)."""
    story = title.rsplit(" - ", 1)[0] if " - " in title else title
    normalized = " ".join(
        "".join(ch if ch.isalnum() else " " for ch in story.lower()).split()
    )
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]
