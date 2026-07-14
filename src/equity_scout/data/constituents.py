"""Index-constituent sources behind a seam. Network scraping is isolated; parsing is unit-tested.

The universe is a union of sources, deduped by ticker. v1's hand-curated global CSV stays a source
(keeps EU/JP/HK/etc. coverage); the S&P 500 source adds breadth. STOXX Europe 600 (multi-exchange,
country→Yahoo-suffix mapping) and Nikkei 225 (code + ".T") plug in as further sources — each maps the
index's native ticker to a Yahoo Finance symbol so yfinance can fetch it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Protocol

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
# The page groups the bullet lists under h3 industry headings (e.g. "Automotive", "Banking") within
# the "Components" section. h2 section headers (e.g. "Weighting", "Statistics") are deliberately
# excluded — one of them wraps an unrelated intro-paragraph mention of a constituent. We wrap each
# h3-h6 heading's text in a sentinel before generic tag-stripping so it survives as its own line and
# parse_nikkei225_text can recover "which heading came before this bullet" from plain text.
_SECTOR_HEADING = re.compile(r"<h[3-6][^>]*>(.*?)</h[3-6]>", re.IGNORECASE | re.DOTALL)
_SECTOR_MARK = "\x00"
_SECTOR_LINE = re.compile(f"{_SECTOR_MARK}(.*?){_SECTOR_MARK}")


def _mark_sector_headings(html: str) -> str:
    def _wrap(match: re.Match[str]) -> str:
        heading_text = _HTML_TAG.sub("", match.group(1)).strip()
        return f"\n{_SECTOR_MARK}{heading_text}{_SECTOR_MARK}\n"

    return _SECTOR_HEADING.sub(_wrap, html)


def strip_html_tags(html: str) -> str:
    """Tag-strip so each bullet becomes its own line '<name> (TYO: NNNN)'. Good enough for this list.

    Sector headings are marked first (see `_mark_sector_headings`) so they survive as their own
    sentinel-delimited line instead of disappearing with the rest of the markup.
    """
    import html as html_module

    marked = _mark_sector_headings(html)
    with_breaks = _BLOCK_BREAK.sub("\n", marked)
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


def _sector_marks(text: str) -> list[tuple[int, str]]:
    """Positions of sector-heading sentinels (see `_mark_sector_headings`), in document order."""
    return [(m.start(), m.group(1).strip()) for m in _SECTOR_LINE.finditer(text)]


def _sector_before(marks: list[tuple[int, str]], pos: int) -> str:
    """The nearest heading at or before `pos`, or 'Unknown' if none precedes it (e.g. an intro-prose
    mention of a constituent, ahead of the first industry heading)."""
    sector = "Unknown"
    for start, name in marks:
        if start > pos:
            break
        sector = name or "Unknown"
    return sector


def parse_nikkei225_text(text: str) -> list[Instrument]:
    """Pure transform: extract '<name> (TYO: NNNN)' entries from Nikkei 225 page text -> Instruments.

    Yahoo symbol = 4-digit TSE code + '.T'. Deduped by code (the page links names that recur); the
    sector is the nearest industry heading (see `_mark_sector_headings`) at or before the entry.
    """
    marks = _sector_marks(text)
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
                sector=_sector_before(marks, match.start()),
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


# --- NASDAQ Trader symbol directory: EVERY US listing, free, no key (plan: universe v3) ---------

_NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# Word-boundary match: a security NAME containing one of these is not common stock
# (warrants/rights/units/preferreds/notes). "United Airlines" must NOT match "unit".
_NON_COMMON_NAME = re.compile(
    r"\b(warrants?|rights?|units?|preferred|preference|notes?|debentures?|funds?)\b",
    re.IGNORECASE,
)  # "funds?": closed-end funds carry no ETF flag in the directory but polluted the first
# 6.6k screen (Calamos CEFs in the defensive bucket, 2026-07-14) — a fund is not an
# operating company and its "fundamentals" are meaningless in a stock factor screen.

# otherlisted.txt Exchange column -> readable label.
_OTHER_EXCHANGES = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}


def _us_listing_instrument(symbol: str, name: str, exchange: str) -> Instrument | None:
    """One US listing row -> Instrument, or None when it is not a screenable common stock.

    Symbols with `$` are preferred-share classes; `.` class shares become Yahoo's `-` form
    (BRK.B -> BRK-B). Sector is honestly "Unknown" here — the directory has none; the live
    pipeline backfills it from yfinance info (see yf_provider.quote_from_info_and_history),
    so sector-relative ranking never silently pools thousands of names into one bucket."""
    symbol = symbol.strip()
    name = name.strip()
    if not symbol or not name or "$" in symbol or _NON_COMMON_NAME.search(name):
        return None
    return Instrument(
        ticker=symbol.replace(".", "-"),
        name=name,
        exchange=exchange,
        region="US",
        currency="USD",
        sector="Unknown",
    )


def _pipe_rows(text: str) -> list[list[str]]:
    """Data rows of a NASDAQ Trader pipe-delimited file (header + 'File Creation Time' footer
    dropped)."""
    lines = [line for line in text.splitlines() if line.strip()]
    return [line.split("|") for line in lines[1:] if not line.startswith("File Creation Time")]


def parse_nasdaq_listed(text: str) -> list[Instrument]:
    """nasdaqlisted.txt: Symbol|Security Name|Market Category|Test Issue|Financial Status|
    Round Lot Size|ETF|NextShares. Test issues and ETFs are dropped."""
    instruments: list[Instrument] = []
    for row in _pipe_rows(text):
        if len(row) < 8:
            continue
        symbol, name, _category, test_issue, _status, _lot, etf, _nextshares = row[:8]
        if test_issue.strip() == "Y" or etf.strip() == "Y":
            continue
        instrument = _us_listing_instrument(symbol, name, "NASDAQ")
        if instrument is not None:
            instruments.append(instrument)
    return instruments


def parse_other_listed(text: str) -> list[Instrument]:
    """otherlisted.txt: ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|
    Test Issue|NASDAQ Symbol. Test issues and ETFs are dropped."""
    instruments: list[Instrument] = []
    for row in _pipe_rows(text):
        if len(row) < 8:
            continue
        symbol, name, exchange_code, _cqs, etf, _lot, test_issue, _nasdaq_symbol = row[:8]
        if test_issue.strip() == "Y" or etf.strip() == "Y":
            continue
        exchange = _OTHER_EXCHANGES.get(exchange_code.strip(), "US")
        instrument = _us_listing_instrument(symbol, name, exchange)
        if instrument is not None:
            instruments.append(instrument)
    return instruments


class NasdaqTraderSource:
    """EVERY US-listed common stock (incl. ADRs — global exposure through a US listing) from the
    NASDAQ Trader symbol directory: free, keyless, officially published, updated nightly. This is
    the "screen everything" source (Nico, 2026-07-14); the completeness gate downstream drops
    thin-data names honestly instead of ranking noise."""

    USER_AGENT = "equity-scout/0.1 (research; contact: nico.sutheimer@bekumoo.de)"

    def fetch(self) -> list[Instrument]:
        import httpx

        instruments: list[Instrument] = []
        for url, parse in ((_NASDAQ_LISTED_URL, parse_nasdaq_listed),
                           (_OTHER_LISTED_URL, parse_other_listed)):
            resp = httpx.get(url, headers={"User-Agent": self.USER_AGENT},
                             timeout=60, follow_redirects=True)
            resp.raise_for_status()
            instruments.extend(parse(resp.text))
        return instruments


# --- Generic Wikipedia index source (universe v4 "whole world", 2026-07-14) ---------------------

_FOOTNOTE = re.compile(r"\s*\[\d+\]\s*$")


def normalize_column(raw: str) -> str:
    """Wikipedia table headers carry footnote refs ('Sector[15]', 'Sector [10]') and stray
    NBSPs; normalize so configs can address columns stably across page edits."""
    return _FOOTNOTE.sub("", str(raw).replace("\xa0", " ")).strip().lower()


@dataclass(frozen=True)
class IndexConfig:
    """One Wikipedia constituents table -> Instruments, declaratively.

    `row_to_yahoo` gets the normalized record (lowercased, footnote-free keys; string values)
    and returns the Yahoo symbol or None to skip the row (honest skip over a guessed symbol).
    `min_expected` is a sanity floor: refresh warns when a source shrinks below it.
    """

    name: str
    url: str
    match_columns: frozenset[str] | set[str]
    name_column: str
    sector_column: str | None
    row_to_yahoo: Callable[[dict[str, str]], str | None]
    region: str
    currency: str
    exchange: str
    min_expected: int


def _normalize_record(record: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in record.items():
        text = "" if value is None else str(value).strip()
        if text.lower() == "nan":
            text = ""
        out[normalize_column(key)] = text
    return out


def parse_index_records(records: list[dict], config: IndexConfig) -> list[Instrument]:
    """Pure transform: raw table records + config -> Instruments. Rows without a mappable
    symbol or a name are skipped."""
    out: list[Instrument] = []
    for raw in records:
        rec = _normalize_record(raw)
        yahoo = config.row_to_yahoo(rec)
        name = rec.get(config.name_column, "")
        if not yahoo or not name:
            continue
        sector = rec.get(config.sector_column, "") if config.sector_column else ""
        out.append(
            Instrument(
                ticker=yahoo,
                name=name,
                exchange=config.exchange,
                region=config.region,
                currency=config.currency,
                sector=sector or "Unknown",
            )
        )
    return out


def _digits_zfill_suffix(
    field: str, width: int, suffix: str
) -> Callable[[dict[str, str]], str | None]:
    """Mapper factory: extract digits from `field`, zero-pad to `width`, append `suffix`.
    Covers Hang Seng ('SEHK: 5' -> 0005.HK) and KOSPI ('090430' -> 090430.KS)."""

    def _map(rec: dict[str, str]) -> str | None:
        digits = "".join(ch for ch in rec.get(field, "") if ch.isdigit())
        return f"{digits.zfill(width)}{suffix}" if digits else None

    return _map


def _symbol_suffix(
    field: str, suffix: str, dot_to_dash: bool = False
) -> Callable[[dict[str, str]], str | None]:
    """Mapper factory: take the symbol as-is (optionally Yahoo's '.'->'-'), append `suffix`."""

    def _map(rec: dict[str, str]) -> str | None:
        base = rec.get(field, "").strip().upper()
        if not base:
            return None
        if base.endswith(".0"):  # pandas may parse an all-numeric code column as float
            base = base[:-2]
        if dot_to_dash:
            base = base.replace(".", "-")
        return f"{base}{suffix}"

    return _map


def _csi300_row_to_yahoo(rec: dict[str, str]) -> str | None:
    """CSI 300: 6-digit code + exchange column ('Shanghai' -> .SS, 'Shenzhen' -> .SZ)."""
    digits = "".join(ch for ch in rec.get("ticker", "") if ch.isdigit())
    if len(digits) != 6:
        return None
    exchange = rec.get("exchange", "").lower()
    if "shanghai" in exchange:
        return f"{digits}.SS"
    if "shenzhen" in exchange:
        return f"{digits}.SZ"
    return None


def find_index_table(html: str, match_columns: set[str] | frozenset[str]) -> list[dict]:
    """Records of the first page table whose normalized column set covers `match_columns`.
    Page order is not guaranteed (STOXX precedent), so detection is by columns, not position."""
    import io

    import pandas as pd

    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:  # no tables in page
        return []
    for table in tables:
        normalized = {normalize_column(c) for c in table.columns}
        if set(match_columns).issubset(normalized):
            return table.to_dict("records")
    return []


class WikipediaIndexSource:
    """Config-driven Wikipedia constituents scraper. One class serves every standard-table
    index page; odd pages (Nikkei bullets) keep their bespoke sources."""

    USER_AGENT = "equity-scout/0.1 (research; contact: nico.sutheimer@bekumoo.de)"

    def __init__(self, config: IndexConfig) -> None:
        self.config = config

    def _get(self) -> str:
        import httpx

        resp = httpx.get(self.config.url, headers={"User-Agent": self.USER_AGENT},
                         timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def fetch(self) -> list[Instrument]:
        records = find_index_table(self._get(), set(self.config.match_columns))
        return parse_index_records(records, self.config)


# Verified against the live pages 2026-07-14 (table shapes in the plan doc). Taiwan 50 is
# deliberately absent: no usable en.wikipedia constituents table exists (404), and the
# zh.wikipedia layout has paired columns, Chinese-only names and no sectors — TSMC is covered
# through its NYSE ADR anyway. Brazil rides the B3 listing page; the Ibovespa page has no
# constituents table.
INDEX_CONFIGS: list[IndexConfig] = [
    IndexConfig(
        name="Hang Seng Index", url="https://en.wikipedia.org/wiki/Hang_Seng_Index",
        match_columns={"ticker", "name", "sub-index"}, name_column="name",
        sector_column="sub-index", row_to_yahoo=_digits_zfill_suffix("ticker", 4, ".HK"),
        region="HK", currency="HKD", exchange="SEHK", min_expected=60,
    ),
    IndexConfig(
        name="CSI 300", url="https://en.wikipedia.org/wiki/CSI_300_Index",
        match_columns={"ticker", "company", "segment", "exchange"}, name_column="company",
        sector_column="segment", row_to_yahoo=_csi300_row_to_yahoo,
        region="CN", currency="CNY", exchange="SSE/SZSE", min_expected=250,
    ),
    IndexConfig(
        name="KOSPI 200", url="https://en.wikipedia.org/wiki/KOSPI_200",
        match_columns={"company", "symbol", "gics sector"}, name_column="company",
        sector_column="gics sector", row_to_yahoo=_digits_zfill_suffix("symbol", 6, ".KS"),
        region="KR", currency="KRW", exchange="KRX", min_expected=150,
    ),
    IndexConfig(
        name="NIFTY 50", url="https://en.wikipedia.org/wiki/NIFTY_50",
        match_columns={"company name", "symbol", "sector"}, name_column="company name",
        sector_column="sector", row_to_yahoo=_symbol_suffix("symbol", ".NS"),
        region="IN", currency="INR", exchange="NSE", min_expected=40,
    ),
    IndexConfig(
        name="NIFTY Next 50", url="https://en.wikipedia.org/wiki/NIFTY_Next_50",
        match_columns={"company name", "symbol", "sector"}, name_column="company name",
        sector_column="sector", row_to_yahoo=_symbol_suffix("symbol", ".NS"),
        region="IN", currency="INR", exchange="NSE", min_expected=40,
    ),
    IndexConfig(
        name="S&P/TSX Composite", url="https://en.wikipedia.org/wiki/S%26P/TSX_Composite_Index",
        match_columns={"ticker", "company", "sector"}, name_column="company",
        sector_column="sector", row_to_yahoo=_symbol_suffix("ticker", ".TO", dot_to_dash=True),
        region="CA", currency="CAD", exchange="TSX", min_expected=150,
    ),
    IndexConfig(
        name="S&P/ASX 200", url="https://en.wikipedia.org/wiki/S%26P/ASX_200",
        match_columns={"code", "company", "sector"}, name_column="company",
        sector_column="sector", row_to_yahoo=_symbol_suffix("code", ".AX"),
        region="AU", currency="AUD", exchange="ASX", min_expected=150,
    ),
    IndexConfig(
        name="B3 listed companies",
        url="https://en.wikipedia.org/wiki/List_of_companies_listed_on_B3",
        match_columns={"company", "ticker", "industry"}, name_column="company",
        sector_column="industry", row_to_yahoo=_symbol_suffix("ticker", ".SA"),
        region="BR", currency="BRL", exchange="B3", min_expected=60,
    ),
]
