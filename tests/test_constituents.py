from equity_scout.data.constituents import (
    combine_sources,
    dedupe_by_ticker,
    parse_nikkei225_text,
    parse_sp500_records,
    parse_stoxx600_records,
    strip_html_tags,
    stoxx_yahoo_ticker,
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


def test_stoxx_yahoo_ticker_maps_country_to_suffix():
    assert stoxx_yahoo_ticker("SAP", "Germany") == "SAP.DE"
    assert stoxx_yahoo_ticker("NESN", "Switzerland") == "NESN.SW"
    assert stoxx_yahoo_ticker("SHEL", "United Kingdom") == "SHEL.L"


def test_stoxx_yahoo_ticker_unknown_country_is_none():
    assert stoxx_yahoo_ticker("XYZ", "Atlantis") is None
    assert stoxx_yahoo_ticker("", "Germany") is None  # empty ticker is unmappable


def test_parse_stoxx600_skips_unmappable_country():
    records = [
        {"Ticker": "NESN", "Company": "Nestle", "ICB Sector": "Food", "Country": "Switzerland"},
        {"Ticker": "GSK", "Company": "GSK plc", "ICB Sector": "Health Care",
         "Country": "United Kingdom"},
        {"Ticker": "XX", "Company": "Unmappable", "ICB Sector": "?", "Country": "Atlantis"},
    ]
    out = parse_stoxx600_records(records)
    assert [i.ticker for i in out] == ["NESN.SW", "GSK.L"]
    assert out[0].region == "EU" and out[0].currency == "CHF"
    assert out[1].currency == "GBP" and out[1].sector == "Health Care"


def test_parse_nikkei225_text_extracts_code_and_appends_t():
    text = (
        "Toyota Motor Corp. (TYO: 7203)\n"
        "Sony Group Corporation (TYO: 6758)\n"
        "Toyota Motor Corp. (TYO: 7203)\n"  # duplicate code -> deduped
    )
    out = parse_nikkei225_text(text)
    assert [i.ticker for i in out] == ["7203.T", "6758.T"]
    assert out[0].region == "JP" and out[0].currency == "JPY"
    assert out[0].name == "Toyota Motor Corp."


def test_parse_nikkei225_trims_leading_prose_from_first_entry():
    # The intro sentence shares a line with the first constituent on the real page.
    text = "the company with the largest influence on the index is Tokyo Electron (TYO: 8035)\n"
    out = parse_nikkei225_text(text)
    assert out[0].ticker == "8035.T"
    assert out[0].name == "Tokyo Electron"


def test_strip_html_tags_breaks_list_items_into_lines():
    # Each <li> becomes its own line so the Nikkei name regex can't reach across entries into prose.
    html = (
        "<p>As of 2026 the biggest is Tokyo Electron</p>"
        "<ul><li><a>Honda Motor</a> Co., Ltd. (<a>TYO</a>: <a>7267</a>)</li>"
        "<li><a>Sony</a> Group (<a>TYO</a>: <a>6758</a>)</li></ul>"
    )
    out = parse_nikkei225_text(strip_html_tags(html))
    assert [i.ticker for i in out] == ["7267.T", "6758.T"]
    assert out[0].name == "Honda Motor Co., Ltd."  # no prose leakage from the <p> above
