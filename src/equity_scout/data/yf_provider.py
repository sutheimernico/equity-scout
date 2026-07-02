"""yfinance-backed provider. Network code isolated; pure parsing is unit-tested."""
from __future__ import annotations

import logging
import math
import statistics
import threading

from equity_scout.models import Instrument, Quote

logger = logging.getLogger(__name__)


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


class FetchStats:
    """Thread-safe counters for one run's yfinance fetches (`fetch_all` uses a thread pool).

    Surfaced in the per-run data-quality report (`equity_scout.data_quality`) so a provider that
    gives up after retries shows up as a visible rate instead of a silently smaller universe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.attempted = 0
        self.info_failed = 0
        self.closes_failed = 0

    def record_attempt(self) -> None:
        with self._lock:
            self.attempted += 1

    def record_info_failure(self) -> None:
        with self._lock:
            self.info_failed += 1

    def record_closes_failure(self) -> None:
        with self._lock:
            self.closes_failed += 1

    def summary(self) -> dict:
        with self._lock:
            return {
                "attempted": self.attempted,
                "info_failed": self.info_failed,
                "closes_failed": self.closes_failed,
            }


class YFinanceProvider:
    """Real provider. Imports yfinance lazily so tests never touch the network."""

    def __init__(self, stats: FetchStats | None = None) -> None:
        self._stats = stats

    def fetch_quote(self, instrument: Instrument) -> Quote:
        import yfinance as yf

        from equity_scout.data.fetch import with_retry

        if self._stats is not None:
            self._stats.record_attempt()

        tk = yf.Ticker(instrument.ticker)

        def _info() -> dict:
            return tk.info or {}

        def _closes() -> list[float]:
            hist = tk.history(period="6mo", interval="1d")
            return [float(c) for c in hist["Close"].tolist()] if not hist.empty else []

        # Retry transient failures (e.g. rate limits); fall back to empty on persistent failure
        # so a single bad ticker is gated out, not fatal to the whole run. Logged + counted rather
        # than swallowed silently, so a spike in fetch failures is visible in the data-quality report.
        try:
            info = with_retry(_info, attempts=3)
        except Exception:
            logger.warning("fetch_quote(%s): info fetch failed after retries", instrument.ticker)
            if self._stats is not None:
                self._stats.record_info_failure()
            info = {}
        try:
            closes = with_retry(_closes, attempts=3)
        except Exception:
            logger.warning("fetch_quote(%s): price history fetch failed after retries", instrument.ticker)
            if self._stats is not None:
                self._stats.record_closes_failure()
            closes = []
        return quote_from_info_and_history(instrument, info, closes)
