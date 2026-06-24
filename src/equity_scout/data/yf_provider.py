"""yfinance-backed provider. Network code isolated; pure parsing is unit-tested."""
from __future__ import annotations

import math
import statistics

from equity_scout.models import Instrument, Quote


def _clean_closes(closes: list[float]) -> list[float]:
    """Keep only finite, positive prices — yfinance occasionally returns NaN/0 rows, which would
    otherwise produce NaN returns and crash the volatility calc."""
    return [c for c in closes if isinstance(c, (int, float)) and math.isfinite(c) and c > 0]


def _daily_returns(closes: list[float]) -> list[float]:
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]


def quote_from_info_and_history(
    instrument: Instrument, info: dict, closes: list[float]
) -> Quote:
    """Pure transform: yfinance .info dict + close prices -> Quote. No network here."""
    clean = _clean_closes(closes)
    momentum = (clean[-1] - clean[0]) / clean[0] if len(clean) >= 2 else None
    rets = _daily_returns(clean)
    volatility = statistics.pstdev(rets) if len(rets) >= 2 else None
    return Quote(
        instrument=instrument,
        trailing_pe=info.get("trailingPE"),
        price_to_book=info.get("priceToBook"),
        return_on_equity=info.get("returnOnEquity"),
        profit_margins=info.get("profitMargins"),
        revenue_growth=info.get("revenueGrowth"),
        earnings_growth=info.get("earningsGrowth"),
        momentum_6m=momentum,
        volatility_6m=volatility,
        price=clean[-1] if clean else None,
    )


class YFinanceProvider:
    """Real provider. Imports yfinance lazily so tests never touch the network."""

    def fetch_quote(self, instrument: Instrument) -> Quote:
        import yfinance as yf

        from equity_scout.data.fetch import with_retry

        tk = yf.Ticker(instrument.ticker)

        def _info() -> dict:
            return tk.info or {}

        def _closes() -> list[float]:
            hist = tk.history(period="6mo", interval="1d")
            return [float(c) for c in hist["Close"].tolist()] if not hist.empty else []

        # Retry transient failures (e.g. rate limits); fall back to empty on persistent failure
        # so a single bad ticker is gated out, not fatal to the whole run.
        try:
            info = with_retry(_info, attempts=3)
        except Exception:
            info = {}
        try:
            closes = with_retry(_closes, attempts=3)
        except Exception:
            closes = []
        return quote_from_info_and_history(instrument, info, closes)
