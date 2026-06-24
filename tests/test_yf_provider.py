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
