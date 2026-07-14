"""Press voices per stock: what the internet says beyond analyst targets (Nico
2026-07-15). Reuses the voices module's keyless Google-News RSS + feed parser; headlines
are quoted as-is with no interpretation — Pressestimmen, kein Signal.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from equity_scout.evidence.voices import _http_get_default, parse_feed_dated

_GOOGLE_NEWS = (
    "https://news.google.com/rss/search?q=%22{query}%22%20stock%20when:7d"
    "&hl=en-US&gl=US&ceid=US:en"
)
# Legal-form suffixes only add noise to a news search for the company.
_NAME_SUFFIX = re.compile(
    r"\s*(,?\s+(Inc|Corp|Corporation|Co|Ltd|PLC|plc|AG|SE|SA|NV|KK|Holdings?|Group))\.?\s*$"
)


def clean_company_query(name: str) -> str:
    """Strip legal suffixes (repeatedly: 'X Holdings Inc.') for a focused news query."""
    cleaned = name.strip()
    while True:
        shorter = _NAME_SUFFIX.sub("", cleaned)
        if shorter == cleaned:
            return cleaned
        cleaned = shorter


def fetch_press_lines(
    company_name: str,
    limit: int = 2,
    width: int = 90,
    http_get: Callable[[str], str] = _http_get_default,
) -> list[str]:
    """Up to `limit` recent press headlines about the company, caption-compact.
    Raises nothing: any failure returns [] — press is decoration, never blocks a pitch."""
    query = clean_company_query(company_name)
    if not query:
        return []
    try:
        xml_text = http_get(_GOOGLE_NEWS.format(query=query.replace(" ", "%20")))
        titles = [title for title, _date in parse_feed_dated(xml_text) if title]
    except Exception:  # noqa: BLE001 - keyless RSS is flaky by nature
        return []
    return [t if len(t) <= width else t[: width - 1] + "…" for t in titles[:limit]]
