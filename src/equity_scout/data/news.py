"""Recent news headlines per ticker (yfinance / Yahoo, free). Seam so tests stay offline.

Headlines are context — what's currently being said about a stock — NOT a forecast or a buy signal.
Yahoo's payload nests the fields under 'content' in recent yfinance; the parse is defensive so a
schema tweak degrades to fewer headlines, never a crash.
"""
from __future__ import annotations

import dataclasses
from typing import Protocol

from equity_scout.models import Pick


def parse_news(raw: list[dict] | None, limit: int = 3) -> list[dict]:
    """Pure: normalise yfinance .news items to {title, publisher, published, link}."""
    items: list[dict] = []
    for entry in raw or []:
        content = entry.get("content", entry)
        title = content.get("title")
        if not title:
            continue
        provider = content.get("provider")
        publisher = provider.get("displayName", "") if isinstance(provider, dict) else (content.get("publisher") or "")
        canonical = content.get("canonicalUrl")
        link = canonical.get("url", "") if isinstance(canonical, dict) else (content.get("link") or "")
        published = content.get("pubDate") or content.get("displayTime") or ""
        items.append({"title": title, "publisher": publisher, "published": published[:10], "link": link})
        if len(items) >= limit:
            break
    return items


class NewsProvider(Protocol):
    def news_for(self, ticker: str) -> list[dict]:
        ...


class FakeNews:
    """Deterministic, offline."""

    def __init__(self, by_ticker: dict[str, list[dict]] | None = None) -> None:
        self._by_ticker = by_ticker or {}

    def news_for(self, ticker: str) -> list[dict]:
        return self._by_ticker.get(ticker, [])


class YFinanceNews:
    """Real impl: Yahoo headlines via yfinance. Lazy import; never raises on a bad ticker."""

    def __init__(self, limit: int = 3) -> None:
        self._limit = limit

    def news_for(self, ticker: str) -> list[dict]:
        import yfinance as yf

        try:
            raw = yf.Ticker(ticker).news
        except Exception:
            return []
        return parse_news(raw, self._limit)


def attach_news(
    buckets: dict[str, list[Pick]],
    provider: NewsProvider | None,
    max_per_bucket: int | None = None,
) -> dict[str, list[Pick]]:
    """Attach recent headlines to picks. provider=None -> unchanged. max_per_bucket caps network
    calls to the top picks (news is fetched per ticker, so we only do it for what's shown)."""
    if provider is None:
        return buckets
    out: dict[str, list[Pick]] = {}
    for bucket, picks in buckets.items():
        out[bucket] = [
            dataclasses.replace(pick, news=provider.news_for(pick.instrument.ticker))
            if (max_per_bucket is None or pick.rank <= max_per_bucket)
            else pick
            for pick in picks
        ]
    return out
