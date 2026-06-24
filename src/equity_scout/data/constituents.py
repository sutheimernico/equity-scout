"""Index-constituent sources behind a seam. Network scraping is isolated; parsing is unit-tested.

The universe is a union of sources, deduped by ticker. v1's hand-curated global CSV stays a source
(keeps EU/JP/HK/etc. coverage); the S&P 500 source adds breadth. More indices (STOXX 600, Nikkei 225)
plug in as additional sources later — each needs its own exchange→Yahoo-suffix mapping.
"""
from __future__ import annotations

from typing import Protocol

from equity_scout.models import Instrument
from equity_scout.universe import load_universe


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
