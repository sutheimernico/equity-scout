"""Generic Wikipedia index source: pure parsing, config-driven."""
from equity_scout.data.constituents import (
    IndexConfig,
    normalize_column,
    parse_index_records,
)


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
