"""Historical news with SECOND-level timestamps — the input for the latency-decay measurement.

Nico's question (2026-08-17): should we scrape many sources to be faster than everyone else?
That is answerable instead of arguable, and this module supplies the data to answer it. Alpaca's
news endpoint serves the Benzinga wire back to 2016 with `created_at` at second resolution
(verified: `2016-01-04T11:15:03Z`). Paired with minute bars, that yields the only number that
matters for the question: **how fast does the reaction decay?**

- If a measurable move is still there 5 minutes after the wire, latency is not the binding
  constraint and a scraping network buys nothing.
- If it is gone in 30 seconds, no scraping setup helps either, because our signal-to-fill path
  is ~5 seconds and the competition is co-located at microseconds.

What this module does NOT claim: that Benzinga is the fastest possible source. It claims to be a
CONSISTENT, timestamped, decade-deep record — which is what a decay curve needs. The publication
delay between the underlying event and the wire is part of what gets measured, not hidden.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

NEWS_BASE = "https://data.alpaca.markets/v1beta1/news"
DATA_BASE_PATH = "data/news"
PAGE_LIMIT = 50  # Alpaca's per-call maximum for this endpoint
COLUMNS = ("id", "created_at", "symbols", "headline", "source")
RETRY_STATUS = (429, 500, 502, 503, 504)  # worth waiting for; anything else raises immediately
MAX_RETRIES = 6


class NewsHistoryError(RuntimeError):
    """Fetch failed in a way the caller must not read as 'no news'."""


def news_path(year: int, *, root: Path | str = DATA_BASE_PATH) -> Path:
    return Path(root) / f"news-{year}.csv.gz"


def parse_news_page(payload: dict) -> tuple[pd.DataFrame, str | None]:
    """One Alpaca news page -> (frame, next_page_token). Items without a usable timestamp or
    headline are dropped rather than repaired — a guessed timestamp would destroy the very
    measurement this data exists for."""
    items = payload.get("news") or []
    token = payload.get("next_page_token")
    rows = []
    for item in items:
        stamp, headline = item.get("created_at"), item.get("headline")
        if not stamp or not headline:
            continue
        rows.append({
            # The wire id is what makes deduplication possible at all: re-published items and
            # page overlaps would otherwise count one story as several "independent" events.
            "id": str(item.get("id") or ""),
            "created_at": stamp,
            "symbols": ",".join(item.get("symbols") or []),
            "headline": headline,
            "source": item.get("source") or "",
        })
    if not rows:
        return pd.DataFrame(columns=list(COLUMNS)), token
    frame = pd.DataFrame(rows)
    frame["created_at"] = pd.to_datetime(frame["created_at"], utc=True, format="ISO8601")
    return frame.sort_values("created_at").reset_index(drop=True), token


def save_year(frame: pd.DataFrame, year: int, *, root: Path | str = DATA_BASE_PATH) -> Path:
    path = news_path(year, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, compression="gzip", index=False)
    return path


def dedupe_news(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per wire item: by `id` where present, by (created_at, headline) otherwise.

    Without this a re-published story counts as several "independent" events and every
    downstream t-statistic is inflated by the duplicate factor.
    """
    if frame.empty:
        return frame
    if "id" in frame.columns:
        ids = frame["id"].fillna("").astype(str)
        with_id = frame.loc[ids != ""].drop_duplicates(subset=["id"])
        without = frame.loc[ids == ""].drop_duplicates(subset=["created_at", "headline"])
        frame = pd.concat([with_id, without])
    else:
        frame = frame.drop_duplicates(subset=["created_at", "headline"])
    return frame.sort_values("created_at").reset_index(drop=True)


def load_news(years: list[int], *, root: Path | str = DATA_BASE_PATH) -> pd.DataFrame:
    """All stored news of `years`, UTC-stamped, deduplicated and sorted. Missing years are
    simply absent. Files written before the `id` column existed load fine — dedup then falls
    back to (created_at, headline)."""
    parts = []
    for year in years:
        path = news_path(year, root=root)
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        frame["created_at"] = pd.to_datetime(frame["created_at"], utc=True, format="ISO8601")
        frame["symbols"] = frame["symbols"].fillna("")
        parts.append(frame)
    if not parts:
        return pd.DataFrame(columns=list(COLUMNS))
    return dedupe_news(pd.concat(parts))


def items_for_ticker(news: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """News whose symbol list CONTAINS the ticker.

    Exact membership, not substring: a substring test would match 'V' against every headline
    tagged 'NVDA' or 'VZ' and silently inflate the sample for short tickers.
    """
    if news.empty:
        return news
    upper = ticker.upper()
    mask = news["symbols"].apply(lambda s: upper in str(s).split(","))
    return news.loc[mask]


def _get_with_backoff(client, url: str, params: dict, *, year: int):
    """GET with retries on 429/5xx — thousands of pages against a 200/min limit WILL hit 429,
    and treating that as fatal would abort a whole year over a speed bump. Honours Retry-After
    when the server sends one; anything not retryable raises immediately."""
    import time as _time

    for attempt in range(MAX_RETRIES):
        response = client.get(url, params=params)
        if response.status_code == 200:
            return response
        if response.status_code not in RETRY_STATUS or attempt == MAX_RETRIES - 1:
            raise NewsHistoryError(
                f"news {year}: HTTP {response.status_code} {response.text[:160]}"
            )
        retry_after = response.headers.get("retry-after")
        wait = float(retry_after) if retry_after else min(2.0 ** attempt, 30.0)
        _time.sleep(wait)
    raise NewsHistoryError(f"news {year}: retries exhausted")  # pragma: no cover


def fetch_news_year(year: int, *, tickers: list[str] | None = None) -> pd.DataFrame:
    """Every news item of one year (optionally restricted to `tickers`), following paging,
    deduplicated by wire id."""
    import httpx

    from equity_scout.alpaca_broker import auth_headers

    pages: list[pd.DataFrame] = []
    token: str | None = None
    with httpx.Client(headers=auth_headers(), timeout=60.0) as client:
        while True:
            params: dict = {
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "limit": PAGE_LIMIT,
                "sort": "asc",
            }
            if tickers:
                params["symbols"] = ",".join(tickers)
            if token:
                params["page_token"] = token
            response = _get_with_backoff(client, NEWS_BASE, params, year=year)
            frame, token = parse_news_page(response.json())
            if not frame.empty:
                pages.append(frame)
            if not token:
                break
    if not pages:
        return pd.DataFrame(columns=list(COLUMNS))
    return dedupe_news(pd.concat(pages))
