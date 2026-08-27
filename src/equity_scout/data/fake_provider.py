"""Deterministic in-memory provider for tests and offline runs."""
from __future__ import annotations

from equity_scout.models import Instrument, Quote


class FakeProvider:
    def __init__(self, quotes: dict[str, dict] | None = None) -> None:
        self._quotes = quotes or {}

    def fetch_quote(self, instrument: Instrument) -> Quote:
        m = self._quotes.get(instrument.ticker, {})
        return Quote(
            instrument=instrument,
            trailing_pe=m.get("trailing_pe"),
            price_to_book=m.get("price_to_book"),
            return_on_equity=m.get("return_on_equity"),
            profit_margins=m.get("profit_margins"),
            revenue_growth=m.get("revenue_growth"),
            earnings_growth=m.get("earnings_growth"),
            momentum_6m=m.get("momentum_6m"),
            volatility_6m=m.get("volatility_6m"),
            price=m.get("price"),
            # Der Liquiditätsfilter (liquidity.py) läuft in der echten Pipeline mit. Ohne
            # Vorgabe liefert der Fake einen investierbaren Titel, damit ein Test, der den
            # Filter nicht meint, nicht an ihm scheitert; wer ihn testen will, setzt die
            # Werte ausdrücklich.
            market_cap=m.get("market_cap", 5_000_000_000.0),
            avg_volume=m.get("avg_volume", 2_000_000.0),
        )
