"""EUR conversion for pitch captions: Nico thinks in Euro, tickers quote in JPY/USD/….

One yfinance FX lookup per currency per process, cached — a pitch batch touches at most
a handful of currencies. Failure returns None and the caption simply omits the € figure.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_RATE_CACHE: dict[str, float | None] = {}
# UK stocks quote in pence (GBp); Yahoo's FX symbol is GBP — convert via /100.
_PENCE = "GBp"


def eur_rate(currency: str | None) -> float | None:
    """EUR per 1 unit of `currency`, or None (unknown currency, EUR itself, or fetch
    failure). Cached per process."""
    if not currency or currency.upper() == "EUR":
        return None
    normalized = "GBP" if currency == _PENCE else currency.upper()
    if normalized in _RATE_CACHE:
        rate = _RATE_CACHE[normalized]
    else:
        rate = _fetch_rate(normalized)
        _RATE_CACHE[normalized] = rate
    if rate is None:
        return None
    return rate / 100.0 if currency == _PENCE else rate


def _fetch_rate(currency: str) -> float | None:
    import yfinance as yf

    try:
        hist = yf.Ticker(f"{currency}EUR=X").history(period="5d", interval="1d")
        if hist.empty:
            return None
        return float(hist["Close"].tolist()[-1])
    except Exception as exc:  # noqa: BLE001 - FX is decoration, never blocks a pitch
        logger.warning("eur_rate(%s) failed: %r", currency, exc)
        return None
