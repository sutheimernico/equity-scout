"""Index-constituent sources behind a seam. Network scraping is isolated; parsing is unit-tested.

The universe is a union of sources, deduped by ticker. v1's hand-curated global CSV stays a source
(keeps EU/JP/HK/etc. coverage); the S&P 500 source adds breadth. STOXX Europe 600 (multi-exchange,
country→Yahoo-suffix mapping) and Nikkei 225 (code + ".T") plug in as further sources — each maps the
index's native ticker to a Yahoo Finance symbol so yfinance can fetch it.
"""
from __future__ import annotations

import re
from typing import Protocol

from equity_scout.models import Instrument
from equity_scout.universe import load_universe

# STOXX 600 lists a bare ticker plus a Country column; Yahoo Finance needs an exchange suffix. We map
# each country to its dominant exchange's Yahoo suffix. Confirmed against Yahoo's exchange-suffix help
# page. Countries whose listing exchange is ambiguous here (Luxembourg, Greece, Poland) are mapped to
# their primary venue; a name we cannot map confidently is skipped rather than guessed.
STOXX_COUNTRY_SUFFIX: dict[str, str] = {
    "United Kingdom": ".L",   # London Stock Exchange
    "France": ".PA",          # Euronext Paris
    "Germany": ".DE",         # Xetra
    "Netherlands": ".AS",     # Euronext Amsterdam
    "Switzerland": ".SW",     # SIX Swiss
    "Italy": ".MI",           # Borsa Italiana
    "Spain": ".MC",           # Bolsa de Madrid
    "Sweden": ".ST",          # Nasdaq Stockholm
    "Belgium": ".BR",         # Euronext Brussels
    "Norway": ".OL",          # Oslo Bors
    "Denmark": ".CO",         # Nasdaq Copenhagen
    "Finland": ".HE",         # Nasdaq Helsinki
    "Austria": ".VI",         # Vienna
    "Portugal": ".LS",        # Euronext Lisbon
    "Ireland": ".IR",         # Euronext Dublin
}

# Country → (region bucket, currency) for the Instrument fields. Region keeps the dashboard's coarse
# EU/US/JP grouping; currency is the listing currency (UK quotes in pence but the field stays GBP).
_STOXX_COUNTRY_META: dict[str, tuple[str, str]] = {
    "United Kingdom": ("EU", "GBP"),
    "France": ("EU", "EUR"),
    "Germany": ("EU", "EUR"),
    "Netherlands": ("EU", "EUR"),
    "Switzerland": ("EU", "CHF"),
    "Italy": ("EU", "EUR"),
    "Spain": ("EU", "EUR"),
    "Sweden": ("EU", "SEK"),
    "Belgium": ("EU", "EUR"),
    "Norway": ("EU", "NOK"),
    "Denmark": ("EU", "DKK"),
    "Finland": ("EU", "EUR"),
    "Austria": ("EU", "EUR"),
    "Portugal": ("EU", "EUR"),
    "Ireland": ("EU", "EUR"),
}


class ConstituentSource(Protocol):
    def fetch(self) -> list[Instrument]:
        ...


def dedupe_by_ticker(instruments: list[Instrument]) -> list[Instrument]:
    """Keep first occurrence per ticker (earlier sources win)."""
    seen: set[str] = set()
    out: list[Instrument] = []
    for inst in instruments:
        if inst.ticker not in seen:
            seen.add(inst.ticker)
            out.append(inst)
    return out


def combine_sources(sources: list[ConstituentSource]) -> list[Instrument]:
    merged: list[Instrument] = []
    for src in sources:
        merged.extend(src.fetch())
    return dedupe_by_ticker(merged)


def parse_sp500_records(records: list[dict]) -> list[Instrument]:
    """Pure transform of Wikipedia 'List of S&P 500 companies' table records -> Instruments.

    Yahoo uses '-' where the index uses '.' (e.g. BRK.B -> BRK-B).
    """
    out: list[Instrument] = []
    for r in records:
        symbol = str(r.get("Symbol", "")).strip().replace(".", "-")
        if not symbol:
            continue
        out.append(
            Instrument(
                ticker=symbol,
                name=str(r.get("Security", symbol)).strip(),
                exchange="US",
                region="US",
                currency="USD",
                sector=str(r.get("GICS Sector", "Unknown")).strip(),
            )
        )
    return out


class CsvConstituentSource:
    """Wraps a static CSV (e.g. the hand-curated global v1 universe) as a source."""

    def __init__(self, csv_path: str) -> None:
        self._csv_path = csv_path

    def fetch(self) -> list[Instrument]:
        return load_universe(self._csv_path)


class WikipediaSP500Source:
    """Scrapes the S&P 500 list from Wikipedia. Lazy imports so tests never hit the network.

    Fetches with an explicit, contactable User-Agent (Wikipedia 403s the urllib default) and feeds
    the HTML to pandas — keeps us a polite client, same spirit as the SEC fair-access rule.
    """

    URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    USER_AGENT = "equity-scout/0.1 (research; contact: nico.sutheimer@bekumoo.de)"

    def fetch(self) -> list[Instrument]:
        import io

        import httpx
        import pandas as pd

        resp = httpx.get(self.URL, headers={"User-Agent": self.USER_AGENT},
                         timeout=30, follow_redirects=True)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        records = tables[0].to_dict("records")
        return parse_sp500_records(records)


def stoxx_yahoo_ticker(bare_ticker: str, country: str) -> str | None:
    """Map a STOXX 600 (bare ticker, country) pair to a Yahoo symbol, or None if unmappable.

    Yahoo wants '.' replaced where the index uses one, then the country's exchange suffix appended.
    Unknown countries return None so the caller skips them rather than fetching a wrong symbol.
    """
    suffix = STOXX_COUNTRY_SUFFIX.get(country.strip())
    if suffix is None:
        return None
    base = bare_ticker.strip().replace(".", "-")
    if not base:
        return None
    return f"{base}{suffix}"


def parse_stoxx600_records(records: list[dict]) -> list[Instrument]:
    """Pure transform of the Wikipedia 'STOXX Europe 600' table records -> Instruments.

    Columns: Ticker | Company | ICB Sector | Country | Headquarters. Rows whose country has no known
    Yahoo suffix are dropped (honest skip over a guessed symbol).
    """
    out: list[Instrument] = []
    for r in records:
        country = str(r.get("Country", "")).strip()
        yahoo = stoxx_yahoo_ticker(str(r.get("Ticker", "")), country)
        if yahoo is None:
            continue
        region, currency = _STOXX_COUNTRY_META.get(country, ("EU", "EUR"))
        out.append(
            Instrument(
                ticker=yahoo,
                name=str(r.get("Company", yahoo)).strip(),
                exchange=STOXX_COUNTRY_SUFFIX[country].lstrip("."),
                region=region,
                currency=currency,
                sector=str(r.get("ICB Sector", "Unknown")).strip(),
            )
        )
    return out


# Nikkei 225's Wikipedia page lists members as sector-grouped bullets, e.g.
# "Toyota Motor Corp. (TYO: 7203)" — not an HTML table. We pull the company name + 4-digit code with a
# regex over tag-stripped text; the Tokyo code + ".T" is the Yahoo symbol.
_NIKKEI_ENTRY = re.compile(r"([^()\n]+?)\s*\(\s*TYO:\s*(\d{4})\s*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
# Block-level tags become newlines first, so each bullet stays one line and the name regex (which
# stops at a newline) can't reach back across entries into surrounding prose.
_BLOCK_BREAK = re.compile(r"</?(?:li|ul|ol|p|br|tr|div)\b[^>]*>", re.IGNORECASE)


def strip_html_tags(html: str) -> str:
    """Tag-strip so each bullet becomes its own line '<name> (TYO: NNNN)'. Good enough for this list."""
    import html as html_module

    with_breaks = _BLOCK_BREAK.sub("\n", html)
    return html_module.unescape(_HTML_TAG.sub("", with_breaks))


def _clean_nikkei_name(raw: str) -> str:
    """Trim a captured name to the company part.

    The intro paragraph can sit on the same line as the first constituent (e.g. "...the largest
    influence on the index is Tokyo Electron (TYO: 8035)"), so a captured name may carry a leading
    prose sentence. Real Nikkei names top out near 40 chars, so only an implausibly long capture
    (> 50) is trimmed, and only by a single split on a sentence break — narrow blast radius: a
    well-formed name is never long enough to trigger this. Prefer the sentence-ending '. '; fall back
    to ' is ' (the intro sentence's verb) only when there's no period to split on.
    """
    name = raw.strip()
    if len(name) <= 50:
        return name
    sep = ". " if ". " in name else (" is " if " is " in name else None)
    return name.rsplit(sep, 1)[-1].strip() if sep else name


def parse_nikkei225_text(text: str) -> list[Instrument]:
    """Pure transform: extract '<name> (TYO: NNNN)' entries from Nikkei 225 page text -> Instruments.

    Yahoo symbol = 4-digit TSE code + '.T'. Deduped by code (the page links names that recur).
    """
    out: list[Instrument] = []
    seen: set[str] = set()
    for match in _NIKKEI_ENTRY.finditer(text):
        name = _clean_nikkei_name(match.group(1))
        code = match.group(2)
        if code in seen:
            continue
        seen.add(code)
        out.append(
            Instrument(
                ticker=f"{code}.T",
                name=name,
                exchange="TSE",
                region="JP",
                currency="JPY",
                sector="Unknown",  # the page groups by sector in headings, not per-row columns
            )
        )
    return out


class WikipediaStoxx600Source:
    """Scrapes the STOXX Europe 600 list from Wikipedia. Lazy imports so tests never hit the network."""

    URL = "https://en.wikipedia.org/wiki/STOXX_Europe_600"
    USER_AGENT = "equity-scout/0.1 (research; contact: nico.sutheimer@bekumoo.de)"

    def fetch(self) -> list[Instrument]:
        import io

        import httpx
        import pandas as pd

        resp = httpx.get(self.URL, headers={"User-Agent": self.USER_AGENT},
                         timeout=30, follow_redirects=True)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        # Find the constituents table by its columns (page order is not guaranteed).
        for table in tables:
            cols = {str(c) for c in table.columns}
            if {"Ticker", "Company", "Country"}.issubset(cols):
                return parse_stoxx600_records(table.to_dict("records"))
        return []


class WikipediaNikkei225Source:
    """Scrapes the Nikkei 225 list from Wikipedia (sector-bulleted text, not a table)."""

    URL = "https://en.wikipedia.org/wiki/Nikkei_225"
    USER_AGENT = "equity-scout/0.1 (research; contact: nico.sutheimer@bekumoo.de)"

    def fetch(self) -> list[Instrument]:
        import httpx

        resp = httpx.get(self.URL, headers={"User-Agent": self.USER_AGENT},
                         timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return parse_nikkei225_text(strip_html_tags(resp.text))
