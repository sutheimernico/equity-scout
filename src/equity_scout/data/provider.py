"""Seam for market data. Real impl uses yfinance; tests use the fake."""
from __future__ import annotations

from typing import Protocol

from equity_scout.models import Instrument, Quote


class MarketDataProvider(Protocol):
    def fetch_quote(self, instrument: Instrument) -> Quote:
        """Return a Quote with metrics; missing metrics are None. Must not raise on missing data."""
        ...
