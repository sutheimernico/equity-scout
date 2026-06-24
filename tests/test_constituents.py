from equity_scout.data.constituents import (
    combine_sources,
    dedupe_by_ticker,
    parse_sp500_records,
)
from equity_scout.models import Instrument


def test_parse_sp500_maps_dot_to_dash_and_fields():
    records = [
        {"Symbol": "AAPL", "Security": "Apple Inc.", "GICS Sector": "Information Technology"},
        {"Symbol": "BRK.B", "Security": "Berkshire Hathaway", "GICS Sector": "Financials"},
    ]
    out = parse_sp500_records(records)
    assert out[0].ticker == "AAPL"
    assert out[1].ticker == "BRK-B"  # Yahoo uses dash
    assert out[1].region == "US" and out[1].currency == "USD"


def test_parse_sp500_skips_empty_symbol():
    assert parse_sp500_records([{"Symbol": "", "Security": "x"}]) == []


def test_dedupe_keeps_first():
    a = Instrument("AAPL", "Apple A", "US", "US", "USD", "Tech")
    b = Instrument("AAPL", "Apple B", "US", "US", "USD", "Tech")
    c = Instrument("MSFT", "Microsoft", "US", "US", "USD", "Tech")
    out = dedupe_by_ticker([a, b, c])
    assert [i.ticker for i in out] == ["AAPL", "MSFT"]
    assert out[0].name == "Apple A"  # first wins


class _FakeSource:
    def __init__(self, instruments):
        self._instruments = instruments

    def fetch(self):
        return self._instruments


def test_combine_sources_unions_and_dedupes():
    s1 = _FakeSource([Instrument("AAPL", "Apple", "US", "US", "USD", "Tech")])
    s2 = _FakeSource([
        Instrument("AAPL", "Apple dup", "US", "US", "USD", "Tech"),
        Instrument("SAP.DE", "SAP", "XETRA", "EU", "EUR", "Tech"),
    ])
    out = combine_sources([s1, s2])
    assert sorted(i.ticker for i in out) == ["AAPL", "SAP.DE"]
