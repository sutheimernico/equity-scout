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


def test_parse_nikkei225_assigns_sector_from_preceding_h3_heading():
    html = (
        '<div class="mw-heading mw-heading3"><h3 id="Automotive">Automotive</h3></div>'
        "<ul><li><a>Honda Motor</a> Co., Ltd. (<a>TYO</a>: <a>7267</a>)</li></ul>"
        '<div class="mw-heading mw-heading3"><h3 id="Banking">Banking</h3></div>'
        "<ul><li><a>Mitsubishi UFJ</a> (<a>TYO</a>: <a>8306</a>)</li></ul>"
    )
    out = parse_nikkei225_text(strip_html_tags(html))
    assert [i.sector for i in out] == ["Automotive", "Banking"]


def test_parse_nikkei225_entry_before_any_heading_is_unknown_sector():
    html = "<p>Tokyo Electron (<a>TYO</a>: <a>8035</a>) is the top constituent by weight.</p>"
    out = parse_nikkei225_text(strip_html_tags(html))
    assert out[0].sector == "Unknown"


def test_parse_nikkei225_ignores_h2_section_headings():
    # h2 top-level sections (e.g. "Weighting") must not be mistaken for an industry heading — the
    # real page has exactly this shape (an h2-level intro mention ahead of the h3 industry list).
    html = (
        '<div class="mw-heading mw-heading2"><h2 id="Weighting">Weighting</h2></div>'
        "<p>Tokyo Electron (<a>TYO</a>: <a>8035</a>) has the largest weight.</p>"
        '<div class="mw-heading mw-heading3"><h3 id="Electric_machinery">Electric machinery</h3></div>'
        "<ul><li>Tokyo Electron (<a>TYO</a>: <a>8035</a>)</li></ul>"
    )
    out = parse_nikkei225_text(strip_html_tags(html))
    assert len(out) == 1  # deduped by code — the earlier (intro) mention wins
    assert out[0].sector == "Unknown"  # not "Weighting"


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


NASDAQ_LISTED_FIXTURE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
ZTEST|Test Issue Co|Q|Y|N|100|N|N
QQQ|Invesco QQQ Trust|G|N|N|100|Y|N
UAL|United Airlines Holdings, Inc. - Common Stock|Q|N|N|100|N|N
ABCW|ABC Corp Warrants expiring 2030|Q|N|N|100|N|N
File Creation Time: 0714202522:01|||||||"""

OTHER_LISTED_FIXTURE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. Class B|N|BRK B|N|100|N|BRK=B
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY
XYZ$A|XYZ Corp Preferred Series A|N|XYZ pA|N|100|N|XYZ-A
TM|Toyota Motor Corporation American Depositary Shares|N|TM|N|100|N|TM
File Creation Time: 0714202522:01|||||||"""


def test_parse_nasdaq_listed_keeps_common_stock_only():
    from equity_scout.data.constituents import parse_nasdaq_listed

    instruments = parse_nasdaq_listed(NASDAQ_LISTED_FIXTURE)
    tickers = [i.ticker for i in instruments]
    assert tickers == ["AAPL", "UAL"]  # test issue, ETF and warrants dropped; UAL not a "unit"
    assert instruments[0].exchange == "NASDAQ"
    assert instruments[0].sector == "Unknown"  # backfilled live from yfinance info


def test_parse_other_listed_maps_symbols_and_filters():
    from equity_scout.data.constituents import parse_other_listed

    instruments = parse_other_listed(OTHER_LISTED_FIXTURE)
    tickers = [i.ticker for i in instruments]
    assert tickers == ["BRK-B", "TM"]  # dot -> dash for Yahoo; ETF + preferred ($) dropped
    assert instruments[0].exchange == "NYSE"
    assert instruments[1].name.startswith("Toyota")  # ADRs stay: global exposure via US listing


def test_closed_end_funds_are_not_common_stock():
    from equity_scout.data.constituents import parse_other_listed

    fixture = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
CSQ|Calamos Strategic Total Return Fund|O|CSQ|N|100|N|CSQ
BXP|BXP, Inc. Common Stock|N|BXP|N|100|N|BXP
File Creation Time: 0714202522:01|||||||"""
    tickers = [i.ticker for i in parse_other_listed(fixture)]
    assert tickers == ["BXP"]  # CEF dropped, operating company stays
