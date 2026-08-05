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
# Exchange listing descriptions. The watchlist's Nasdaq-sourced names carry them
# ("Air T, Inc. - Common Stock"), but no news headline ever does. Measured 2026-08-05:
# leaving them in the search phrase cost 4 of the top 12 watchlist stocks ALL headlines.
_LISTING_SUFFIX = re.compile(
    r"\s*[-–]?\s*(Common|Ordinary|Class\s+[A-Z])\s+(Stock|Shares?)\s*$", re.IGNORECASE
)

# Legal-form suffixes only add noise to a news search for the company; these are never
# part of a company's name in a headline, so they always go.
_LEGAL_SUFFIX = re.compile(
    r"\s*(,?\s+(Inc|Corp|Corporation|Co|Ltd|PLC|plc|AG|SE|SA|NV|KK))\.?\s*$"
)

# "Holdings"/"Group" sit between the two: usually noise, but for many Asian conglomerates
# they are what distinguishes the company from a shared family name. Measured 2026-08-05:
# stripping it turned "Yamato Holdings Co., Ltd." (9064.T) into "Yamato", and the news
# summary then described TSE:1967, TSE:5444 and TSE:8127 — three unrelated companies. So
# it is dropped only when at least two words survive.
_NOISE_SUFFIX = re.compile(r"\s*(,?\s+(Holdings?|Group))\.?\s*$", re.IGNORECASE)


def clean_company_query(name: str) -> str:
    """Focused news-search phrase for a company name.

    Order matters: the listing description comes off first (it sits outside the legal
    form), then legal forms are stripped repeatedly ('X Holdings Inc.'), and only then is
    a trailing "Holdings"/"Group" considered — and kept if removing it would leave a
    single word.
    """
    cleaned = _LISTING_SUFFIX.sub("", name.strip()).strip()
    while True:
        shorter = _LEGAL_SUFFIX.sub("", cleaned)
        if shorter == cleaned:
            break
        cleaned = shorter
    without_noise = _NOISE_SUFFIX.sub("", cleaned).strip()
    if without_noise and without_noise != cleaned and len(without_noise.split()) >= 2:
        return without_noise
    return cleaned


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
