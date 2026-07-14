"""Generic Wikipedia index source: pure parsing, config-driven."""
from equity_scout.data.constituents import (
    INDEX_CONFIGS,
    IndexConfig,
    normalize_column,
    parse_index_records,
)


def _cfg(name: str) -> IndexConfig:
    return next(c for c in INDEX_CONFIGS if c.name == name)


def _hk_row_to_yahoo(rec: dict) -> str | None:
    digits = "".join(ch for ch in rec.get("ticker", "") if ch.isdigit())
    return f"{digits.zfill(4)}.HK" if digits else None


HANG_SENG = IndexConfig(
    name="Hang Seng Index",
    url="https://en.wikipedia.org/wiki/Hang_Seng_Index",
    match_columns={"ticker", "name", "sub-index"},
    name_column="name",
    sector_column="sub-index",
    row_to_yahoo=_hk_row_to_yahoo,
    region="HK",
    currency="HKD",
    exchange="SEHK",
    min_expected=60,
)


def test_normalize_column_strips_footnotes_and_case():
    assert normalize_column("Sector[15]") == "sector"
    assert normalize_column("Sector [10]") == "sector"
    assert normalize_column("Company Name") == "company name"
    assert normalize_column("  Sub-index\xa0") == "sub-index"


def test_parse_index_records_maps_rows():
    records = [
        {"Ticker": "SEHK:\xa05", "Name": "HSBC Holdings plc", "Sub-index": "Finance"},
        {"Ticker": "SEHK: 700", "Name": "Tencent Holdings", "Sub-index": "Commerce"},
    ]
    out = parse_index_records(records, HANG_SENG)
    assert [i.ticker for i in out] == ["0005.HK", "0700.HK"]
    assert out[0].name == "HSBC Holdings plc"
    assert out[0].sector == "Finance"
    assert out[0].region == "HK"
    assert out[0].currency == "HKD"
    assert out[0].exchange == "SEHK"


def test_parse_index_records_skips_unmappable_and_empty_rows():
    records = [
        {"Ticker": "", "Name": "Ghost", "Sub-index": "None"},
        {"Ticker": "nan", "Name": "nan", "Sub-index": "nan"},
        {"Ticker": "SEHK: 1", "Name": "CKH Holdings", "Sub-index": "Commerce"},
    ]
    out = parse_index_records(records, HANG_SENG)
    assert [i.ticker for i in out] == ["0001.HK"]


def test_parse_index_records_without_sector_column_uses_unknown():
    cfg = IndexConfig(
        name="X", url="u", match_columns={"symbol", "company"},
        name_column="company", sector_column=None,
        row_to_yahoo=lambda rec: rec.get("symbol") or None,
        region="XX", currency="XXX", exchange="XX", min_expected=1,
    )
    out = parse_index_records([{"Symbol": "ABC", "Company": "Abc Corp"}], cfg)
    assert out[0].sector == "Unknown"


def test_csi300_routes_exchange_to_suffix():
    cfg = _cfg("CSI 300")
    records = [
        {"Ticker": "SSE: 600519", "Company": "Kweichow Moutai",
         "Segment": "Consumer Staples", "Exchange": "Shanghai", "Weighting (%)": "5.9"},
        {"Ticker": "SZSE: 000001", "Company": "Ping An Bank",
         "Segment": "Financials", "Exchange": "Shenzhen", "Weighting (%)": "1.0"},
    ]
    out = parse_index_records(records, cfg)
    assert [i.ticker for i in out] == ["600519.SS", "000001.SZ"]
    assert out[0].sector == "Consumer Staples"
    assert out[0].region == "CN"


def test_kospi200_keeps_leading_zeros():
    cfg = _cfg("KOSPI 200")
    out = parse_index_records(
        [{"Company": "Amorepacific", "Symbol": "090430", "GICS Sector": "Consumer Staples"}], cfg
    )
    assert out[0].ticker == "090430.KS"


def test_nifty_footnoted_sector_column_is_read():
    cfg = _cfg("NIFTY 50")
    out = parse_index_records(
        [{"Company name": "Adani Enterprises", "Symbol": "ADANIENT",
          "Sector[15]": "Metals & Mining", "Date added[16]": "2022"}], cfg
    )
    assert out[0].ticker == "ADANIENT.NS"
    assert out[0].sector == "Metals & Mining"


def test_tsx_class_shares_and_units_map_to_yahoo_dashes():
    cfg = _cfg("S&P/TSX Composite")
    records = [
        {"Ticker": "VNP", "Company": "5N Plus Inc.", "Sector [10]": "Materials",
         "Industry [10]": "x"},
        {"Ticker": "CTC.A", "Company": "Canadian Tire A", "Sector [10]": "Retail",
         "Industry [10]": "x"},
    ]
    out = parse_index_records(records, cfg)
    assert [i.ticker for i in out] == ["VNP.TO", "CTC-A.TO"]


def test_asx_numeric_code_stays_string():
    cfg = _cfg("S&P/ASX 200")
    out = parse_index_records(
        [{"Code": "360", "Company": "Life360", "Sector": "Information Technology",
          "Market Capitalisation (A$)": "1", "Headquarters": "San Mateo"}], cfg
    )
    assert out[0].ticker == "360.AX"


def test_b3_ticker_gets_sa_suffix():
    cfg = _cfg("B3 listed companies")
    out = parse_index_records(
        [{"Company": "Alpargatas", "Ticker": "ALPA4", "Industry": "clothing",
          "Headquarters": "São Paulo"}], cfg
    )
    assert out[0].ticker == "ALPA4.SA"
    assert out[0].region == "BR"


def test_all_configs_have_positive_floor_and_unique_names():
    # 8 configs covering 7 new regions (India spans the NIFTY 50 + NIFTY Next 50 pages).
    names = [c.name for c in INDEX_CONFIGS]
    assert len(names) == len(set(names)) == 8
    assert all(c.min_expected > 0 for c in INDEX_CONFIGS)
