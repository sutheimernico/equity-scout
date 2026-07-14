"""Overlay stored sectors onto Unknowns; harvest newly discovered sectors after a fetch.

Includes the regression test for the cache-hit sector loss: a sector fetched live once must
still be present on a later run that serves the same ticker from cache.
"""
from dataclasses import replace

from equity_scout.data.cache import CachedProvider, QuoteCache
from equity_scout.models import Instrument, Quote
from equity_scout.pipeline import harvest_sectors
from equity_scout.universe import apply_meta_overlay


def _inst(ticker: str, sector: str = "Unknown") -> Instrument:
    return Instrument(ticker=ticker, name=ticker, exchange="X", region="US",
                      currency="USD", sector=sector)


def _quote(inst: Instrument) -> Quote:
    return Quote(instrument=inst, trailing_pe=10.0, price_to_book=1.0, return_on_equity=0.1,
                 profit_margins=0.1, revenue_growth=0.1, earnings_growth=0.1,
                 momentum_6m=0.1, volatility_6m=0.01, price=100.0)


def test_overlay_fills_only_unknown_sectors():
    universe = [_inst("A"), _inst("B", sector="Financials"), _inst("C")]
    out = apply_meta_overlay(universe, {"A": "Technology", "B": "WRONG", "D": "Energy"})
    assert [i.sector for i in out] == ["Technology", "Financials", "Unknown"]


def test_harvest_returns_only_newly_discovered_sectors():
    universe = [_inst("A"), _inst("B", sector="Financials")]
    quotes = [_quote(_inst("A", sector="Technology")), _quote(_inst("B", sector="Financials"))]
    assert harvest_sectors(universe, quotes) == {"A": "Technology"}


def test_harvest_ignores_still_unknown():
    universe = [_inst("A")]
    assert harvest_sectors(universe, [_quote(_inst("A"))]) == {}


class _SectorProvider:
    """Fake live provider that knows A's sector (simulates yfinance .info backfill)."""

    def fetch_quote(self, instrument: Instrument) -> Quote:
        return _quote(replace(instrument, sector="Technology"))


def test_regression_cache_hit_keeps_meta_sector(tmp_path):
    """Run 1 fetches live (sector discovered + harvested). Run 2 hits the cache — without the
    meta overlay the sector reverts to Unknown; with it, ranking still sees 'Technology'."""
    cache = QuoteCache(tmp_path / "c.db")
    universe_run1 = [_inst("A")]
    provider = CachedProvider(_SectorProvider(), cache, run_date="2026-07-14")
    quotes_run1 = [provider.fetch_quote(i) for i in universe_run1]
    harvested = harvest_sectors(universe_run1, quotes_run1)
    assert harvested == {"A": "Technology"}

    # Run 2, same cache, fresh enough: the instrument passed in decides the sector.
    universe_run2 = apply_meta_overlay([_inst("A")], harvested)
    provider2 = CachedProvider(_SectorProvider(), cache, run_date="2026-07-14", max_age_days=7)
    quotes_run2 = [provider2.fetch_quote(i) for i in universe_run2]
    assert quotes_run2[0].instrument.sector == "Technology"
