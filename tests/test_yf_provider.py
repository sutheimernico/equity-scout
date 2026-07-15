import datetime
import sys
import types

import equity_scout.data.fetch as fetch_mod
from equity_scout.data.yf_provider import (
    FetchStats,
    YFinanceProvider,
    fetch_earnings_dates,
    quote_from_info_and_history,
)
from equity_scout.models import Instrument


def test_quote_from_info_computes_momentum():
    inst = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Tech")
    info = {"trailingPE": 30.0, "priceToBook": 40.0, "returnOnEquity": 1.5,
            "profitMargins": 0.25, "revenueGrowth": 0.08, "earningsGrowth": 0.10}
    closes = [100.0] * 5 + [110.0]  # +10% over the window
    q = quote_from_info_and_history(inst, info, closes)
    assert q.trailing_pe == 30.0
    assert abs(q.momentum_6m - 0.10) < 1e-9


def test_quote_from_info_handles_missing():
    inst = Instrument("X", "X", "E", "EM", "XXX", "Misc")
    q = quote_from_info_and_history(inst, {}, [])
    assert q.trailing_pe is None
    assert q.momentum_6m is None
    assert q.volatility_6m is None


def test_volatility_from_varying_prices_is_positive():
    inst = Instrument("X", "X", "E", "US", "USD", "Tech")
    q = quote_from_info_and_history(inst, {}, [100.0, 101.0, 100.0, 102.0, 99.0, 103.0])
    assert q.volatility_6m is not None and q.volatility_6m > 0


def test_volatility_flat_prices_is_zero():
    inst = Instrument("X", "X", "E", "US", "USD", "Tech")
    q = quote_from_info_and_history(inst, {}, [100.0] * 6)
    assert q.volatility_6m == 0.0


def test_handles_nan_and_zero_closes_without_crashing():
    inst = Instrument("X", "X", "E", "US", "USD", "Tech")
    # yfinance sometimes returns NaN / 0 rows — only the two valid prices should count.
    q = quote_from_info_and_history(inst, {}, [100.0, float("nan"), 0.0, 110.0])
    assert q.price == 110.0
    assert q.momentum_6m is not None and abs(q.momentum_6m - 0.10) < 1e-9


# --- FetchStats + fetch_quote observability (mocks with_retry, never touches the network) ---


def _always_fails(fn, attempts=3, **kwargs):
    raise RuntimeError("boom")


def test_fetch_quote_records_info_and_closes_failures(monkeypatch):
    monkeypatch.setattr(fetch_mod, "with_retry", _always_fails)
    stats = FetchStats()
    inst = Instrument("X", "X", "E", "US", "USD", "Tech")

    quote = YFinanceProvider(stats=stats).fetch_quote(inst)

    assert quote.trailing_pe is None and quote.price is None  # both fell back to empty
    assert stats.summary() == {"attempted": 1, "info_failed": 1, "closes_failed": 1}


def test_fetch_quote_without_stats_injected_does_not_crash(monkeypatch):
    monkeypatch.setattr(fetch_mod, "with_retry", _always_fails)
    inst = Instrument("X", "X", "E", "US", "USD", "Tech")

    quote = YFinanceProvider().fetch_quote(inst)  # stats=None is the default

    assert quote.price is None


def test_fetch_stats_summary_counts_correctly():
    stats = FetchStats()
    for _ in range(3):
        stats.record_attempt()
    stats.record_info_failure()
    assert stats.summary() == {"attempted": 3, "info_failed": 1, "closes_failed": 0}


def test_quote_backfills_unknown_sector_from_info():
    from equity_scout.models import Instrument

    unknown = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Unknown")
    quote = quote_from_info_and_history(unknown, {"sector": "Technology"}, [1.0, 2.0])
    assert quote.instrument.sector == "Technology"

    known = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Information Technology")
    quote = quote_from_info_and_history(known, {"sector": "Technology"}, [1.0, 2.0])
    assert quote.instrument.sector == "Information Technology"  # CSV sector wins when present

    no_info = quote_from_info_and_history(unknown, {}, [1.0, 2.0])
    assert no_info.instrument.sector == "Unknown"  # honest absence, never guessed


# --- fetch_earnings_dates (lazy import, same fake-module pattern as test_fundamentals.py) ---


def _fake_yfinance(calendar) -> types.ModuleType:
    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = lambda ticker: types.SimpleNamespace(calendar=calendar)
    return fake_yf


def test_fetch_earnings_dates_returns_sorted_iso_strings(monkeypatch):
    calendar = {"Earnings Date": [datetime.date(2026, 7, 23), datetime.date(2026, 7, 22)]}
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(calendar))
    assert fetch_earnings_dates("AAPL") == ["2026-07-22", "2026-07-23"]


def test_fetch_earnings_dates_empty_when_calendar_has_no_earnings_key(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance({}))
    assert fetch_earnings_dates("XYZ") == []


def test_fetch_earnings_dates_returns_empty_on_none_calendar(monkeypatch):
    """yfinance's own .calendar can be None (e.g. delisted) — never crash on it."""
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(None))
    assert fetch_earnings_dates("XYZ") == []


def test_fetch_earnings_dates_returns_empty_on_exception(monkeypatch):
    fake_yf = types.ModuleType("yfinance")

    def boom(ticker):
        raise RuntimeError("network down")

    fake_yf.Ticker = boom
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)
    assert fetch_earnings_dates("AAPL") == []


def test_fetch_earnings_dates_ignores_unparseable_entries(monkeypatch):
    """Defensive: a malformed entry (neither a date nor an ISO string) is dropped,
    not raised — honest partial data beats a crashed fetch."""
    calendar = {"Earnings Date": [datetime.date(2026, 7, 22), None, 42]}
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(calendar))
    assert fetch_earnings_dates("AAPL") == ["2026-07-22"]
