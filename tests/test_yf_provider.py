from equity_scout.data.yf_provider import quote_from_info_and_history
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
