"""yfinance-backed provider. Network code isolated; pure parsing is unit-tested."""
from __future__ import annotations

import logging
import math
import statistics
import threading
from dataclasses import replace

from equity_scout.models import Instrument, Quote

logger = logging.getLogger(__name__)


def _clean_closes(closes: list[float]) -> list[float]:
    """Keep only finite, positive prices — yfinance occasionally returns NaN/0 rows, which would
    otherwise produce NaN returns and crash the volatility calc."""
    return [c for c in closes if isinstance(c, (int, float)) and math.isfinite(c) and c > 0]


def _daily_returns(closes: list[float]) -> list[float]:
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]


def _proximity_to_52w_high(last: float | None, high: object) -> float | None:
    """last close / info's fiftyTwoWeekHigh — free with the info call (the history fetch
    only covers 6 months, so the high cannot be computed locally). Defensive like
    factors._clean: .info is untyped JSON, anything non-numeric is an honest None."""
    if last is None or isinstance(high, bool) or not isinstance(high, (int, float)):
        return None
    if not math.isfinite(high) or high <= 0:
        return None
    return last / float(high)


def _positive(value: object) -> float | None:
    """Untypisierte JSON-Zahl -> positiver float, sonst None. `.info` liefert für dünne
    Titel gern 0 oder None; eine 0 als Börsenwert würde den Liquiditätsfilter härter
    machen als beabsichtigt (0 < Schwelle), eine None sagt ehrlich „unbekannt"."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def quote_from_info_and_history(
    instrument: Instrument, info: dict, closes: list[float]
) -> Quote:
    """Pure transform: yfinance .info dict + close prices -> Quote. No network here.

    Sector backfill: the NASDAQ-Trader universe source has no sector column, and an "Unknown"
    sector would silently pool thousands of names into one meaningless sector-relative ranking
    bucket (the 2026-07-02 Nikkei lesson). When the CSV sector is unknown and yfinance knows
    one, the quote carries the known sector."""
    sector = info.get("sector")
    if sector and instrument.sector in ("", "Unknown"):
        instrument = replace(instrument, sector=str(sector))
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
        high_52w_proximity=_proximity_to_52w_high(
            clean[-1] if clean else None, info.get("fiftyTwoWeekHigh")
        ),
        market_cap=_positive(info.get("marketCap")),
        avg_volume=_positive(info.get("averageVolume")),
    )


def fetch_dividend_yield(ticker: str) -> float | None:
    """TTM dividend yield (annualised decimal, e.g. 0.03 = 3%) for ``ticker`` via yfinance, or None.

    Reads ``trailingAnnualDividendYield`` — the realised trailing-twelve-month yield, reliably a
    decimal fraction. ``dividendYield`` is deliberately NOT used as a fallback: yfinance has returned
    it inconsistently (sometimes a percent like 3.0, sometimes 0.03), and guessing the scale would
    fabricate a number. None — no data, common for non-US names — is honest: the caller credits no
    dividend rather than an estimate. Single attempt (no retry): a missing/failed yield just means
    "no dividend this run" and self-heals next run, so it isn't worth the retry latency. Lazy import
    keeps this network-free at module load.
    """
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info or {}
        value = info.get("trailingAnnualDividendYield")
        if value is None:
            return None
        value = float(value)
        return value if value >= 0 else None  # NaN and negatives fall through to None
    except Exception:  # noqa: BLE001 - any provider hiccup → honest "no dividend"
        return None


def _earnings_dates_from_calendar(calendar: dict) -> list[str]:
    """Pure: extract sorted ISO date strings from a yfinance ``Ticker.calendar`` dict.

    ``calendar["Earnings Date"]`` is normally a list of `datetime.date` objects; entries that
    are already ISO strings (cheap test doubles) are accepted too, and anything else (None,
    an int, ...) is silently dropped rather than raising — one malformed entry should not
    blank out the rest of a real response.
    """
    dates = calendar.get("Earnings Date") or []
    out = []
    for d in dates:
        if hasattr(d, "isoformat"):
            out.append(d.isoformat())
        elif isinstance(d, str):
            out.append(d)
    return sorted(set(out))


def fetch_earnings_dates(ticker: str) -> list[str]:
    """Upcoming earnings dates for ``ticker`` as sorted ISO date strings, or [] if unknown.

    Reads ``Ticker.calendar``, not ``Ticker.earnings_dates``: ``.calendar`` hits Yahoo's
    lightweight quoteSummary ``calendarEvents`` module — the same request family as ``.info``,
    used by ``fetch_dividend_yield`` above — and its "Earnings Date" entry IS Yahoo's own
    upcoming-earnings estimate (usually a one- or two-day window), always forward-looking.
    ``.earnings_dates`` instead scrapes an HTML calendar table that mixes already-reported and
    estimated rows, pushing the "is this date actually upcoming" filtering (and the fragility
    of an HTML-table scrape) onto the caller — an extra failure mode this repo does not need.
    Many non-US tickers have no calendar coverage at all; that surfaces as an honest empty
    list, never a guess. Lazy import + broad except mirror ``fetch_dividend_yield``'s guard.
    """
    try:
        import yfinance as yf

        calendar = yf.Ticker(ticker).calendar
        if not isinstance(calendar, dict):
            return []
        return _earnings_dates_from_calendar(calendar)
    except Exception:  # noqa: BLE001 - any provider hiccup → honest "no earnings known"
        return []


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
