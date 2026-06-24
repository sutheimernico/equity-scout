"""yfinance-backed provider. Network code isolated; pure parsing is unit-tested."""
from __future__ import annotations

from equity_scout.models import Instrument, Quote


def quote_from_info_and_history(
    instrument: Instrument, info: dict, closes: list[float]
) -> Quote:
    """Pure transform: yfinance .info dict + close prices -> Quote. No network here."""
    momentum = None
    if len(closes) >= 2 and closes[0]:
        momentum = (closes[-1] - closes[0]) / closes[0]
    return Quote(
        instrument=instrument,
        trailing_pe=info.get("trailingPE"),
        price_to_book=info.get("priceToBook"),
        return_on_equity=info.get("returnOnEquity"),
        profit_margins=info.get("profitMargins"),
        revenue_growth=info.get("revenueGrowth"),
        earnings_growth=info.get("earningsGrowth"),
        momentum_6m=momentum,
    )


class YFinanceProvider:
    """Real provider. Imports yfinance lazily so tests never touch the network."""

    def fetch_quote(self, instrument: Instrument) -> Quote:
        import yfinance as yf

        tk = yf.Ticker(instrument.ticker)
        try:
            info = tk.info or {}
        except Exception:
            info = {}
        try:
            hist = tk.history(period="6mo", interval="1d")
            closes = [float(c) for c in hist["Close"].tolist()] if not hist.empty else []
        except Exception:
            closes = []
        return quote_from_info_and_history(instrument, info, closes)
