# Global Universe + Instrument Meta + Nightly Prefetch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the universe to 7 new region indices (~+1,150 tickers), persist yfinance-discovered sectors in an `instrument_meta` SQLite table, and warm the quote cache with a nightly prefetch rotation so the weekly screen ranks the full universe.

**Architecture:** One generic, config-driven `WikipediaIndexSource` (pure `parse_index_records` + per-index `IndexConfig` with a `row_to_yahoo` mapper) plugs into the existing constituent-source seam. A new `instrument_meta` table (in `universe_storage.py`) is written by a post-fetch harvest in the pipeline and read by a pure overlay applied at universe load. A new `run_prefetch.py` rotates through universe segments nightly via the existing `CachedProvider`.

**Tech Stack:** Python 3.12, uv, httpx + pandas.read_html (existing pattern), sqlite3, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-07-14-global-universe-and-metadata-design.md`

**Scope deltas vs. spec (verified live 2026-07-14, honest-skip rule):**
- Taiwan 50 DROPPED — en.wikipedia page does not exist (404); zh.wikipedia has only Chinese names, paired columns, no sectors. TSMC is covered via its NYSE ADR (TSM).
- Brazil uses `List_of_companies_listed_on_B3` (88 rows, columns Company/Ticker/Industry) — the Ibovespa page has no constituents table.
- KOSPI 200 page verified: columns Company/Symbol/GICS Sector. NIFTY pages carry footnote suffixes in column names ("Sector[15]") → normalization required.

Verified table shapes (2026-07-14 probe):

| Page | Columns (raw) | Rows |
|---|---|---|
| Hang_Seng_Index | Ticker ("SEHK: 5"), Name, Sub-index | 85 |
| CSI_300_Index | Ticker ("SSE: 600519"), Company, Segment, Exchange ("Shanghai"/"Shenzhen"), Weighting (%) | 300 |
| KOSPI_200 | Company, Symbol ("090430"), GICS Sector | 200 |
| NIFTY_50 | Company name, Symbol, Sector[15], Date added[16] | 51 |
| NIFTY_Next_50 | Company Name, Symbol, Sector | 51 |
| S%26P/TSX_Composite_Index | Ticker ("VNP"), Company, Sector [10], Industry [10] | 221 |
| S%26P/ASX_200 | Code ("360"), Company, Sector, Market Capitalisation (A$), Headquarters | 200 |
| List_of_companies_listed_on_B3 | Company, Ticker ("ALPA4"), Industry, Headquarters | 88 |

---

### Task 1: Column normalization + IndexConfig + pure record parser

**Files:**
- Modify: `src/equity_scout/data/constituents.py` (append after NasdaqTraderSource)
- Test: `tests/test_constituents_generic.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_constituents_generic.py -q`
Expected: FAIL — ImportError (`IndexConfig` not defined).

- [ ] **Step 3: Implement in `constituents.py`**

Append below the NasdaqTraderSource block:

```python
# --- Generic Wikipedia index source (universe v4 "whole world", 2026-07-14) ---------------------

_FOOTNOTE = re.compile(r"\s*\[\d+\]\s*$")


def normalize_column(raw: str) -> str:
    """Wikipedia table headers carry footnote refs ('Sector[15]', 'Sector [10]') and stray
    NBSPs; normalize so configs can address columns stably across page edits."""
    return _FOOTNOTE.sub("", str(raw).replace("\xa0", " ")).strip().lower()


@dataclass(frozen=True)
class IndexConfig:
    """One Wikipedia constituents table -> Instruments, declaratively.

    `row_to_yahoo` gets the normalized record (lowercased, footnote-free keys; string values)
    and returns the Yahoo symbol or None to skip the row (honest skip over a guessed symbol).
    `min_expected` is a sanity floor: refresh warns when a source shrinks below it.
    """

    name: str
    url: str
    match_columns: frozenset[str] | set[str]
    name_column: str
    sector_column: str | None
    row_to_yahoo: Callable[[dict[str, str]], str | None]
    region: str
    currency: str
    exchange: str
    min_expected: int


def _normalize_record(record: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in record.items():
        text = "" if value is None else str(value).strip()
        if text.lower() == "nan":
            text = ""
        out[normalize_column(key)] = text
    return out


def parse_index_records(records: list[dict], config: IndexConfig) -> list[Instrument]:
    """Pure transform: raw table records + config -> Instruments. Rows without a mappable
    symbol or a name are skipped."""
    out: list[Instrument] = []
    for raw in records:
        rec = _normalize_record(raw)
        yahoo = config.row_to_yahoo(rec)
        name = rec.get(config.name_column, "")
        if not yahoo or not name:
            continue
        sector = rec.get(config.sector_column, "") if config.sector_column else ""
        out.append(
            Instrument(
                ticker=yahoo,
                name=name,
                exchange=config.exchange,
                region=config.region,
                currency=config.currency,
                sector=sector or "Unknown",
            )
        )
    return out
```

Imports to add at the top of `constituents.py`:

```python
from dataclasses import dataclass
from typing import Callable, Protocol
```

(`Protocol` is already imported — extend that line, don't duplicate.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_constituents_generic.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/data/constituents.py tests/test_constituents_generic.py
git commit -m "feat(universe): generic config-driven Wikipedia index parser"
```

### Task 2: The seven index configs + symbol mappers

**Files:**
- Modify: `src/equity_scout/data/constituents.py`
- Test: `tests/test_constituents_generic.py` (extend)

- [ ] **Step 1: Write the failing tests (append to test file)**

```python
from equity_scout.data.constituents import INDEX_CONFIGS, parse_index_records


def _cfg(name: str):
    return next(c for c in INDEX_CONFIGS if c.name == name)


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
        {"Ticker": "VNP", "Company": "5N Plus Inc.", "Sector [10]": "Materials", "Industry [10]": "x"},
        {"Ticker": "CTC.A", "Company": "Canadian Tire A", "Sector [10]": "Retail", "Industry [10]": "x"},
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
    names = [c.name for c in INDEX_CONFIGS]
    assert len(names) == len(set(names)) == 7
    assert all(c.min_expected > 0 for c in INDEX_CONFIGS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_constituents_generic.py -q`
Expected: FAIL — ImportError (`INDEX_CONFIGS`).

- [ ] **Step 3: Implement configs (append to `constituents.py`)**

```python
def _digits_zfill_suffix(field: str, width: int, suffix: str) -> Callable[[dict[str, str]], str | None]:
    """Mapper factory: extract digits from `field`, zero-pad to `width`, append `suffix`.
    Covers Hang Seng ('SEHK: 5' -> 0005.HK) and KOSPI ('090430' -> 090430.KS)."""

    def _map(rec: dict[str, str]) -> str | None:
        digits = "".join(ch for ch in rec.get(field, "") if ch.isdigit())
        return f"{digits.zfill(width)}{suffix}" if digits else None

    return _map


def _symbol_suffix(field: str, suffix: str, dot_to_dash: bool = False) -> Callable[[dict[str, str]], str | None]:
    """Mapper factory: take the symbol as-is (optionally Yahoo's '.'->'-'), append `suffix`."""

    def _map(rec: dict[str, str]) -> str | None:
        base = rec.get(field, "").strip().upper()
        if not base:
            return None
        if base.endswith(".0"):  # pandas may parse an all-numeric code column as float
            base = base[:-2]
        if dot_to_dash:
            base = base.replace(".", "-")
        return f"{base}{suffix}"

    return _map


def _csi300_row_to_yahoo(rec: dict[str, str]) -> str | None:
    """CSI 300: 6-digit code + exchange column ('Shanghai' -> .SS, 'Shenzhen' -> .SZ)."""
    digits = "".join(ch for ch in rec.get("ticker", "") if ch.isdigit())
    if len(digits) != 6:
        return None
    exchange = rec.get("exchange", "").lower()
    if "shanghai" in exchange:
        return f"{digits}.SS"
    if "shenzhen" in exchange:
        return f"{digits}.SZ"
    return None


INDEX_CONFIGS: list[IndexConfig] = [
    IndexConfig(
        name="Hang Seng Index", url="https://en.wikipedia.org/wiki/Hang_Seng_Index",
        match_columns={"ticker", "name", "sub-index"}, name_column="name",
        sector_column="sub-index", row_to_yahoo=_digits_zfill_suffix("ticker", 4, ".HK"),
        region="HK", currency="HKD", exchange="SEHK", min_expected=60,
    ),
    IndexConfig(
        name="CSI 300", url="https://en.wikipedia.org/wiki/CSI_300_Index",
        match_columns={"ticker", "company", "segment", "exchange"}, name_column="company",
        sector_column="segment", row_to_yahoo=_csi300_row_to_yahoo,
        region="CN", currency="CNY", exchange="SSE/SZSE", min_expected=250,
    ),
    IndexConfig(
        name="KOSPI 200", url="https://en.wikipedia.org/wiki/KOSPI_200",
        match_columns={"company", "symbol", "gics sector"}, name_column="company",
        sector_column="gics sector", row_to_yahoo=_digits_zfill_suffix("symbol", 6, ".KS"),
        region="KR", currency="KRW", exchange="KRX", min_expected=150,
    ),
    IndexConfig(
        name="NIFTY 50", url="https://en.wikipedia.org/wiki/NIFTY_50",
        match_columns={"company name", "symbol", "sector"}, name_column="company name",
        sector_column="sector", row_to_yahoo=_symbol_suffix("symbol", ".NS"),
        region="IN", currency="INR", exchange="NSE", min_expected=40,
    ),
    IndexConfig(
        name="NIFTY Next 50", url="https://en.wikipedia.org/wiki/NIFTY_Next_50",
        match_columns={"company name", "symbol", "sector"}, name_column="company name",
        sector_column="sector", row_to_yahoo=_symbol_suffix("symbol", ".NS"),
        region="IN", currency="INR", exchange="NSE", min_expected=40,
    ),
    IndexConfig(
        name="S&P/TSX Composite", url="https://en.wikipedia.org/wiki/S%26P/TSX_Composite_Index",
        match_columns={"ticker", "company", "sector"}, name_column="company",
        sector_column="sector", row_to_yahoo=_symbol_suffix("ticker", ".TO", dot_to_dash=True),
        region="CA", currency="CAD", exchange="TSX", min_expected=150,
    ),
    IndexConfig(
        name="S&P/ASX 200", url="https://en.wikipedia.org/wiki/S%26P/ASX_200",
        match_columns={"code", "company", "sector"}, name_column="company",
        sector_column="sector", row_to_yahoo=_symbol_suffix("code", ".AX"),
        region="AU", currency="AUD", exchange="ASX", min_expected=150,
    ),
    IndexConfig(
        name="B3 listed companies", url="https://en.wikipedia.org/wiki/List_of_companies_listed_on_B3",
        match_columns={"company", "ticker", "industry"}, name_column="company",
        sector_column="industry", row_to_yahoo=_symbol_suffix("ticker", ".SA"),
        region="BR", currency="BRL", exchange="B3", min_expected=60,
    ),
]
```

Note: NIFTY 50's raw columns are "Company name" / "Sector[15]" and NIFTY Next 50's are
"Company Name" / "Sector" — after `normalize_column` both become "company name" / "sector",
so one config shape serves both pages. Taiwan 50 is intentionally absent (see scope deltas).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_constituents_generic.py -q`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/data/constituents.py tests/test_constituents_generic.py
git commit -m "feat(universe): index configs for HK/CN/KR/IN/CA/AU/BR"
```

### Task 3: WikipediaIndexSource (network fetch + table detection)

**Files:**
- Modify: `src/equity_scout/data/constituents.py`
- Test: `tests/test_constituents_generic.py` (extend)

- [ ] **Step 1: Write the failing tests (append)**

```python
from equity_scout.data.constituents import WikipediaIndexSource, find_index_table

_FAKE_HTML = """
<html><body>
<table><tr><th>Year</th><th>Closing level</th></tr>
<tr><td>1999</td><td>100</td></tr></table>
<table><tr><th>Ticker</th><th>Name</th><th>Sub-index</th></tr>
<tr><td>SEHK: 5</td><td>HSBC Holdings plc</td><td>Finance</td></tr>
<tr><td>SEHK: 700</td><td>Tencent Holdings</td><td>Commerce</td></tr></table>
</body></html>
"""


def test_find_index_table_picks_by_normalized_columns():
    records = find_index_table(_FAKE_HTML, {"ticker", "name", "sub-index"})
    assert len(records) == 2
    assert records[0]["Name"] == "HSBC Holdings plc"


def test_find_index_table_returns_empty_when_absent():
    assert find_index_table(_FAKE_HTML, {"ticker", "company", "segment", "exchange"}) == []


def test_wikipedia_index_source_parses_fake_html():
    class FakeSource(WikipediaIndexSource):
        def _get(self) -> str:  # override network
            return _FAKE_HTML

    hk = next(c for c in INDEX_CONFIGS if c.name == "Hang Seng Index")
    out = FakeSource(hk).fetch()
    assert [i.ticker for i in out] == ["0005.HK", "0700.HK"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_constituents_generic.py -q`
Expected: FAIL — ImportError (`WikipediaIndexSource`).

- [ ] **Step 3: Implement (append to `constituents.py`)**

```python
def find_index_table(html: str, match_columns: set[str] | frozenset[str]) -> list[dict]:
    """Records of the first page table whose normalized column set covers `match_columns`.
    Page order is not guaranteed (STOXX precedent), so detection is by columns, not position."""
    import io

    import pandas as pd

    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:  # no tables in page
        return []
    for table in tables:
        normalized = {normalize_column(c) for c in table.columns}
        if set(match_columns).issubset(normalized):
            return table.to_dict("records")
    return []


class WikipediaIndexSource:
    """Config-driven Wikipedia constituents scraper. One class serves every standard-table
    index page; odd pages (Nikkei bullets) keep their bespoke sources."""

    USER_AGENT = "equity-scout/0.1 (research; contact: nico.sutheimer@bekumoo.de)"

    def __init__(self, config: IndexConfig) -> None:
        self.config = config

    def _get(self) -> str:
        import httpx

        resp = httpx.get(self.config.url, headers={"User-Agent": self.USER_AGENT},
                         timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def fetch(self) -> list[Instrument]:
        records = find_index_table(self._get(), set(self.config.match_columns))
        return parse_index_records(records, self.config)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_constituents_generic.py -q`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/data/constituents.py tests/test_constituents_generic.py
git commit -m "feat(universe): WikipediaIndexSource with column-set table detection"
```

### Task 4: Wire new sources into refresh + per-source count report

**Files:**
- Modify: `scripts/refresh_universe.py`
- Test: `tests/test_refresh_report.py` (create)

- [ ] **Step 1: Write the failing test**

The count report is pure — extract it into the library so it's testable:
`src/equity_scout/data/constituents.py` gets `source_count_report`.

```python
"""Per-source count report for universe refresh: a silent shrink must be loud."""
from equity_scout.data.constituents import source_count_report


def test_report_flags_sources_below_floor():
    counts = [("Hang Seng Index", 85, 60), ("CSI 300", 12, 250)]
    lines, warnings = source_count_report(counts)
    assert any("Hang Seng Index" in ln and "85" in ln for ln in lines)
    assert warnings == ["CSI 300: 12 rows < floor 250 — page layout may have changed"]


def test_report_no_warnings_when_all_healthy():
    _, warnings = source_count_report([("A", 100, 50)])
    assert warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_refresh_report.py -q`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

Append to `constituents.py`:

```python
def source_count_report(counts: list[tuple[str, int, int]]) -> tuple[list[str], list[str]]:
    """(source, count, floor) triples -> (report lines, warnings for below-floor sources)."""
    lines = [f"  {name:<28} {count:>5} instruments" for name, count, _ in counts]
    warnings = [
        f"{name}: {count} rows < floor {floor} — page layout may have changed"
        for name, count, floor in counts
        if count < floor
    ]
    return lines, warnings
```

In `scripts/refresh_universe.py`, replace the `sources = [...]` block and the
`universe = combine_sources(sources)` line with:

```python
    named_sources: list[tuple[str, ConstituentSource, int]] = [
        ("hand-curated v1 CSV", CsvConstituentSource(args.base_csv), 30),
        ("Wikipedia S&P 500", WikipediaSP500Source(), 400),
        ("Wikipedia STOXX 600", WikipediaStoxx600Source(), 400),
        ("Wikipedia Nikkei 225", WikipediaNikkei225Source(), 150),
    ]
    named_sources += [
        (cfg.name, WikipediaIndexSource(cfg), cfg.min_expected) for cfg in INDEX_CONFIGS
    ]
    # "Screen everything" source stays last: named sources win ticker collisions (richer metadata).
    named_sources.append(("NASDAQ Trader directory", NasdaqTraderSource(), 4000))

    fetched: list[list[Instrument]] = []
    counts: list[tuple[str, int, int]] = []
    for name, source, floor in named_sources:
        instruments = source.fetch()
        fetched.append(instruments)
        counts.append((name, len(instruments), floor))
    universe = dedupe_by_ticker([inst for batch in fetched for inst in batch])

    lines, warnings = source_count_report(counts)
    print("Universe sources:")
    for line in lines:
        print(line)
    for warning in warnings:
        print(f"  WARNING: {warning}")
    print(f"Combined (deduped): {len(universe)}")
```

Update the imports in `refresh_universe.py` accordingly:

```python
from equity_scout.data.constituents import (
    INDEX_CONFIGS,
    ConstituentSource,
    CsvConstituentSource,
    NasdaqTraderSource,
    WikipediaIndexSource,
    WikipediaNikkei225Source,
    WikipediaSP500Source,
    WikipediaStoxx600Source,
    dedupe_by_ticker,
    source_count_report,
)
from equity_scout.models import Instrument
```

(`combine_sources` import is dropped — the inline loop replaces it to collect counts.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_refresh_report.py tests/test_constituents_generic.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/data/constituents.py scripts/refresh_universe.py tests/test_refresh_report.py
git commit -m "feat(universe): wire 7 new index sources into refresh with count report"
```

### Task 5: `instrument_meta` store

**Files:**
- Modify: `src/equity_scout/data/universe_storage.py`
- Test: `tests/test_instrument_meta.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""Persistent instrument metadata: sectors discovered live must survive cache hits."""
from equity_scout.data.universe_storage import (
    init_universe_db,
    load_instrument_meta,
    upsert_instrument_meta,
)


def test_upsert_and_load_roundtrip(tmp_path):
    db = tmp_path / "u.db"
    init_universe_db(db)
    upsert_instrument_meta(db, {"AAPL": "Technology", "KO": "Consumer Defensive"},
                           source="yfinance.info", updated_at="2026-07-14")
    assert load_instrument_meta(db) == {"AAPL": "Technology", "KO": "Consumer Defensive"}


def test_upsert_overwrites_and_empty_dict_is_noop(tmp_path):
    db = tmp_path / "u.db"
    init_universe_db(db)
    upsert_instrument_meta(db, {}, source="s", updated_at="2026-07-14")
    upsert_instrument_meta(db, {"AAPL": "Tech"}, source="s", updated_at="2026-07-14")
    upsert_instrument_meta(db, {"AAPL": "Technology"}, source="s", updated_at="2026-07-15")
    assert load_instrument_meta(db) == {"AAPL": "Technology"}


def test_load_from_missing_table_returns_empty(tmp_path):
    assert load_instrument_meta(tmp_path / "missing.db") == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_instrument_meta.py -q`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement in `universe_storage.py`**

Extend `init_universe_db`'s executescript with (inside the same triple-quoted SQL string):

```sql
            CREATE TABLE IF NOT EXISTS instrument_meta (
                ticker TEXT PRIMARY KEY,
                sector TEXT NOT NULL,
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
```

Append functions:

```python
def upsert_instrument_meta(
    db_path: str | Path, sectors: dict[str, str], source: str, updated_at: str
) -> None:
    """Persist live-discovered sectors. The quote cache stores only metrics, so a sector seen
    on a live fetch would otherwise be lost on every later cache hit (the 2026-07-14 lesson);
    this table makes a once-seen sector durable."""
    if not sectors:
        return
    init_universe_db(db_path)
    with sqlite3.connect(db_path) as con:
        con.executemany(
            "INSERT INTO instrument_meta (ticker, sector, source, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(ticker) DO UPDATE SET sector = excluded.sector, "
            "source = excluded.source, updated_at = excluded.updated_at",
            [(t, s, source, updated_at) for t, s in sectors.items()],
        )


def load_instrument_meta(db_path: str | Path) -> dict[str, str]:
    """ticker -> sector for every stored row; {} when the DB/table doesn't exist yet."""
    if not Path(db_path).exists():
        return {}
    with sqlite3.connect(db_path) as con:
        try:
            rows = con.execute("SELECT ticker, sector FROM instrument_meta").fetchall()
        except sqlite3.OperationalError:
            return {}
    return dict(rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_instrument_meta.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/data/universe_storage.py tests/test_instrument_meta.py
git commit -m "feat(meta): persistent instrument_meta sector store"
```

### Task 6: Sector overlay + post-fetch harvest (pipeline integration)

**Files:**
- Modify: `src/equity_scout/universe.py` (overlay), `src/equity_scout/pipeline.py` (harvest)
- Test: `tests/test_sector_overlay.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""Overlay stored sectors onto Unknowns; harvest newly discovered sectors after a fetch.

Includes the regression test for the cache-hit sector loss: a sector fetched live once must
still be present on a later run that serves the same ticker from cache.
"""
from equity_scout.data.cache import CachedProvider, QuoteCache
from equity_scout.models import Instrument, Quote
from equity_scout.pipeline import harvest_sectors
from equity_scout.universe import apply_meta_overlay


def _inst(ticker: str, sector: str = "Unknown") -> Instrument:
    return Instrument(ticker=ticker, name=ticker, exchange="X", region="US",
                      currency="USD", sector=sector)


def _quote(inst: Instrument) -> Quote:
    return Quote(instrument=inst, trailing_pe=10.0, price_to_book=1.0, return_on_equity=0.1,
                 profit_margins=0.1, revenue_growth=0.1, earnings_growth=0.1,
                 momentum_6m=0.1, volatility_6m=0.01, price=100.0)


def test_overlay_fills_only_unknown_sectors():
    universe = [_inst("A"), _inst("B", sector="Financials"), _inst("C")]
    out = apply_meta_overlay(universe, {"A": "Technology", "B": "WRONG", "D": "Energy"})
    assert [i.sector for i in out] == ["Technology", "Financials", "Unknown"]


def test_harvest_returns_only_newly_discovered_sectors():
    universe = [_inst("A"), _inst("B", sector="Financials")]
    quotes = [_quote(_inst("A", sector="Technology")), _quote(_inst("B", sector="Financials"))]
    assert harvest_sectors(universe, quotes) == {"A": "Technology"}


def test_harvest_ignores_still_unknown():
    universe = [_inst("A")]
    assert harvest_sectors(universe, [_quote(_inst("A"))]) == {}


class _SectorProvider:
    """Fake live provider that knows A's sector (simulates yfinance .info backfill)."""

    def fetch_quote(self, instrument: Instrument) -> Quote:
        from dataclasses import replace
        return _quote(replace(instrument, sector="Technology"))


def test_regression_cache_hit_keeps_meta_sector(tmp_path):
    """Run 1 fetches live (sector discovered + harvested). Run 2 hits the cache — without the
    meta overlay the sector reverts to Unknown; with it, ranking still sees 'Technology'."""
    cache = QuoteCache(tmp_path / "c.db")
    universe_run1 = [_inst("A")]
    provider = CachedProvider(_SectorProvider(), cache, run_date="2026-07-14")
    quotes_run1 = [provider.fetch_quote(i) for i in universe_run1]
    harvested = harvest_sectors(universe_run1, quotes_run1)
    assert harvested == {"A": "Technology"}

    # Run 2, next day, cache fresh enough: instrument passed in decides the sector.
    universe_run2 = apply_meta_overlay([_inst("A")], harvested)
    provider2 = CachedProvider(_SectorProvider(), cache, run_date="2026-07-14", max_age_days=7)
    quotes_run2 = [provider2.fetch_quote(i) for i in universe_run2]
    assert quotes_run2[0].instrument.sector == "Technology"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sector_overlay.py -q`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement**

In `src/equity_scout/universe.py` append (import `replace` from dataclasses at top):

```python
def apply_meta_overlay(
    instruments: list[Instrument], sectors: dict[str, str]
) -> list[Instrument]:
    """Fill 'Unknown' sectors from the persistent instrument_meta store. Never overwrites a
    sector the constituent source itself provided."""
    return [
        replace(inst, sector=sectors[inst.ticker])
        if inst.sector in ("", "Unknown") and sectors.get(inst.ticker)
        else inst
        for inst in instruments
    ]
```

In `src/equity_scout/pipeline.py` append:

```python
def harvest_sectors(universe: list[Instrument], quotes: list[Quote]) -> dict[str, str]:
    """Sectors the fetch discovered for instruments the universe knew as 'Unknown' — the caller
    persists them (pipeline stays DB-free)."""
    unknown = {i.ticker for i in universe if i.sector in ("", "Unknown")}
    return {
        q.instrument.ticker: q.instrument.sector
        for q in quotes
        if q.instrument.ticker in unknown and q.instrument.sector not in ("", "Unknown")
    }
```

And import `Quote` in pipeline.py (`from equity_scout.models import Instrument, Quote, RunResult`).

`run_pipeline` gets the harvest hook — change the signature and the body:

```python
def run_pipeline(
    universe: list[Instrument],
    provider: MarketDataProvider,
    analysis: AnalysisProvider | None = None,
    top_n: int = 10,
    min_metrics: int = 4,
    created_at: str = "",
    max_workers: int = 8,
    llm_top_n: int | None = None,
    news: NewsProvider | None = None,
    news_top_n: int | None = 5,
    fetch_stats: FetchStats | None = None,
    sector_sink: Callable[[dict[str, str]], None] | None = None,
) -> RunResult:
    quotes = fetch_all(provider, universe, max_workers=max_workers)
    if sector_sink is not None:
        sector_sink(harvest_sectors(universe, quotes))
    ...
```

(`from typing import Callable` at top; rest of the body unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sector_overlay.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/equity_scout/universe.py src/equity_scout/pipeline.py tests/test_sector_overlay.py
git commit -m "feat(meta): sector overlay at load + post-fetch harvest hook"
```

### Task 7: Wire overlay/harvest + `--cache-max-age` into run_scout and scheduled run

**Files:**
- Modify: `scripts/run_scout.py`, `src/equity_scout/data/cache.py` (no change needed — `max_age_days` param exists), `scripts/scheduled_run.sh`
- Test: `tests/test_run_scout_wiring.py` only if a CLI test pattern already exists — otherwise this is glue verified by the live smoke in Task 10 (do check `ls tests/ | grep -i scout`).

- [ ] **Step 1: Modify `scripts/run_scout.py`**

Add argument after `--cache-db`:

```python
    ap.add_argument("--cache-max-age", type=int, default=1,
                    help="Serve cached quotes up to N days old (scheduled weekly run uses 7 "
                         "so the nightly prefetch warm-up is actually used).")
```

Replace the provider wiring and pipeline call:

```python
    universe = apply_meta_overlay(load_universe(args.universe), load_instrument_meta(args.db))
    fetch_stats = FetchStats() if args.provider == "yfinance" else None
    base = YFinanceProvider(stats=fetch_stats) if args.provider == "yfinance" else FakeProvider()
    if args.provider == "yfinance" and not args.no_cache:
        provider = CachedProvider(base, QuoteCache(args.cache_db),
                                  run_date=now.date().isoformat(),
                                  max_age_days=args.cache_max_age)
    else:
        provider = base

    def _persist_sectors(sectors: dict[str, str]) -> None:
        upsert_instrument_meta(args.db, sectors, source="yfinance.info",
                               updated_at=now.date().isoformat())

    run = run_pipeline(
        universe, provider, analysis=analysis, top_n=args.top_n,
        created_at=now.isoformat(timespec="seconds"), max_workers=args.max_workers,
        llm_top_n=args.llm_top_n, news=news, news_top_n=args.news_top_n,
        fetch_stats=fetch_stats, sector_sink=_persist_sectors,
    )
```

New imports in run_scout.py:

```python
from equity_scout.data.universe_storage import load_instrument_meta, upsert_instrument_meta
from equity_scout.universe import apply_meta_overlay, load_universe
```

- [ ] **Step 2: Modify `scripts/scheduled_run.sh`** — add one flag to the exec line:

```bash
exec "$REPO_DIR/.venv/bin/python" scripts/run_scout.py \
  --provider yfinance \
  --universe data/universe_combined.csv \
  --db equity_scout.db \
  --cache-max-age 7 \
  --use-llm --llm-top-n 3 \
  --max-workers 6
```

- [ ] **Step 3: Offline smoke** (fake provider ignores cache flags but exercises overlay + sink):

Run: `uv run python scripts/run_scout.py --universe data/universe_v1.csv --db /tmp/es_smoke.db --top-n 3`
Expected: run completes, bucket output prints, exit 0.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (~575).

- [ ] **Step 5: Commit**

```bash
git add scripts/run_scout.py scripts/scheduled_run.sh
git commit -m "feat(scout): meta overlay + sector persistence + --cache-max-age"
```

### Task 8: Nightly prefetch (rotation + script + cron)

**Files:**
- Create: `scripts/run_prefetch.py`, `scripts/nightly_prefetch.sh`
- Modify: `src/equity_scout/data/fetch.py` (rotation helper), `scripts/install_crontab.sh`
- Test: `tests/test_prefetch_rotation.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
"""Prefetch rotation: deterministic per date, full coverage across a rotation cycle."""
from datetime import date

from equity_scout.data.fetch import rotation_segment


def test_same_date_same_segment():
    tickers = [f"T{i}" for i in range(100)]
    a = rotation_segment(tickers, segments=6, on=date(2026, 7, 14))
    b = rotation_segment(tickers, segments=6, on=date(2026, 7, 14))
    assert a == b and len(a) > 0


def test_six_consecutive_days_cover_everything():
    tickers = [f"T{i:03d}" for i in range(100)]
    covered: set[str] = set()
    for day in range(14, 20):
        covered.update(rotation_segment(tickers, segments=6, on=date(2026, 7, day)))
    assert covered == set(tickers)


def test_segments_are_disjoint():
    tickers = [f"T{i:03d}" for i in range(100)]
    seen: set[str] = set()
    for day in range(14, 20):
        seg = set(rotation_segment(tickers, segments=6, on=date(2026, 7, day)))
        assert not (seen & seg)
        seen |= seg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prefetch_rotation.py -q`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement rotation in `fetch.py`**

```python
def rotation_segment(tickers: list[str], segments: int, on: "date") -> list[str]:
    """Tonight's slice of the universe: sorted, split into `segments` contiguous slices, pick by
    day-of-year modulo. Deterministic and stateless — a missed night (WSL off) heals on the next
    pass of the rotation instead of needing a progress table."""
    ordered = sorted(tickers)
    if segments <= 1:
        return ordered
    idx = on.timetuple().tm_yday % segments
    size = -(-len(ordered) // segments)  # ceil division
    return ordered[idx * size:(idx + 1) * size]
```

Add `from datetime import date` to fetch.py imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prefetch_rotation.py -q`
Expected: 3 passed.

- [ ] **Step 5: Create `scripts/run_prefetch.py`**

```python
"""Nightly cache warm-up: fetch one universe segment through the read-through cache.

Purpose: the weekly full screen died on yfinance rate limits (2026-07-14: 5,275 gated, most
"missing price history"). Instead of one marathon run, a gentle nightly rotation keeps the
cache warm; the Monday screen then ranks from cache (--cache-max-age 7) and only live-fetches
misses. Sectors discovered on the way are persisted to instrument_meta.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_UNIVERSE_PATH
from equity_scout.data.cache import CachedProvider, QuoteCache
from equity_scout.data.fetch import fetch_all, rotation_segment
from equity_scout.data.universe_storage import load_instrument_meta, upsert_instrument_meta
from equity_scout.data.yf_provider import FetchStats, YFinanceProvider
from equity_scout.pipeline import harvest_sectors
from equity_scout.universe import apply_meta_overlay, load_universe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=DEFAULT_UNIVERSE_PATH)
    ap.add_argument("--db", default=DEFAULT_DB_PATH)
    ap.add_argument("--cache-db", default="equity_scout_cache.db")
    ap.add_argument("--segments", type=int, default=6)
    ap.add_argument("--max-workers", type=int, default=2,
                    help="Deliberately low — this is a background crawl under the rate limit.")
    ap.add_argument("--cache-max-age", type=int, default=6,
                    help="Skip names fetched within N days (already warm).")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    universe = apply_meta_overlay(load_universe(args.universe), load_instrument_meta(args.db))
    by_ticker = {i.ticker: i for i in universe}
    segment_tickers = rotation_segment(list(by_ticker), segments=args.segments, on=now.date())
    segment = [by_ticker[t] for t in segment_tickers]

    stats = FetchStats()
    provider = CachedProvider(
        YFinanceProvider(stats=stats), QuoteCache(args.cache_db),
        run_date=now.date().isoformat(), max_age_days=args.cache_max_age,
    )
    quotes = fetch_all(provider, segment, max_workers=args.max_workers)
    sectors = harvest_sectors(segment, quotes)
    upsert_instrument_meta(args.db, sectors, source="yfinance.info",
                           updated_at=now.date().isoformat())

    s = stats.summary()
    print(
        f"prefetch {now.date().isoformat()}: segment {len(segment)}/{len(universe)} tickers, "
        f"{s['attempted']} live fetches, {s['info_failed']} info-failures, "
        f"{s['closes_failed']} price-failures, {len(sectors)} sectors persisted"
    )


if __name__ == "__main__":
    main()
```

Note: `stats.attempted` counts only live fetches (cache hits never reach the provider), so the
printed line directly shows how warm the segment already was.

- [ ] **Step 6: Create `scripts/nightly_prefetch.sh`** (pattern: scheduled_run.sh)

```bash
#!/usr/bin/env bash
# Nightly universe prefetch: warms one segment of the quote cache so the weekly screen can
# rank the full universe from cache instead of dying on yfinance rate limits.
# Calls .venv/bin/python directly because cron's minimal PATH has no uv.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

exec "$REPO_DIR/.venv/bin/python" scripts/run_prefetch.py \
  --universe data/universe_combined.csv \
  --db equity_scout.db
```

Run: `chmod +x scripts/nightly_prefetch.sh`

- [ ] **Step 7: Add the cron line to `install_crontab.sh`**

After `NIGHTLY_LINE=...` add:

```bash
PREFETCH_LINE="45 0 * * 1-6 flock -n /tmp/equity-scout-prefetch.lock ${REPO_DIR}/scripts/nightly_prefetch.sh >> ${REPO_DIR}/prefetch.log 2>&1"
```

And extend the for-loop list: `for line in "$CHAIN_LINE" "$RECEIVER_LINE" "$INTRADAY_LINE" "$NIGHTLY_LINE" "$PREFETCH_LINE"; do`.
Also update the header comment (add "(e) the nightly prefetch at 00:45 Mon–Sat").

- [ ] **Step 8: Full suite + ruff**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all pass, no lint errors.

- [ ] **Step 9: Commit**

```bash
git add src/equity_scout/data/fetch.py scripts/run_prefetch.py scripts/nightly_prefetch.sh scripts/install_crontab.sh tests/test_prefetch_rotation.py
git commit -m "feat(prefetch): nightly cache warm-up rotation + cron line"
```

### Task 9: Frontend region check

**Files:**
- Inspect: `frontend/src/` (grep for region handling), fix only if regions are hardcoded.

- [ ] **Step 1: Check whether regions are data-driven**

Run: `grep -rn "region" frontend/src --include=*.ts --include=*.tsx -l` then inspect hits.
Expected: region lists derived from API data → nothing to do. If a hardcoded
`["US","EU","JP",...]` list exists, extend it with `HK CN KR IN CA AU BR` and run
`cd frontend && npm run build` to verify. Commit only if changed:

```bash
git add frontend/src && git commit -m "feat(frontend): surface new universe regions"
```

### Task 10: Live universe refresh + provenance + smoke

**Files:**
- Modify (generated): `data/universe_combined.csv`, `data/universe_combined.PROVENANCE.md`

- [ ] **Step 1: Run the refresh live**

Run: `uv run python scripts/refresh_universe.py`
Expected: per-source count table prints; no floor warnings; combined ≈ 7.4–7.6k.

- [ ] **Step 2: Sanity-check the CSV**

Run: `uv run python - <<'EOF'`
```python
import csv
from collections import Counter
rows = list(csv.DictReader(open("data/universe_combined.csv")))
print(len(rows), Counter(r["region"] for r in rows).most_common())
assert len(rows) > 7000
for t in ("0700.HK", "600519.SS", "005930.KS", "RELIANCE.NS", "RY.TO", "BHP.AX", "ALPA4.SA"):
    assert any(r["ticker"] == t for r in rows), f"missing {t}"
print("spot checks OK")
EOF
```
Expected: region counts show HK/CN/KR/IN/CA/AU/BR > 0; spot checks OK. (005930.KS Samsung and
RY.TO existed in v1 CSV already — they must dedupe to ONE row each, not duplicate.)

- [ ] **Step 3: Update `data/universe_combined.PROVENANCE.md`** — rewrite reflecting the new
source list, per-source counts from Step 1, and the Taiwan/Ibovespa honest skips.

- [ ] **Step 4: Tiny live scout smoke (rate-limit-friendly)**

Run: `head -60 data/universe_combined.csv > /tmp/es_univ_sample.csv && uv run python scripts/run_scout.py --provider yfinance --universe /tmp/es_univ_sample.csv --db /tmp/es_live_smoke.db --cache-db /tmp/es_live_cache.db --top-n 3 --max-workers 2 --no-news`
Expected: completes; then verify meta persistence:
`uv run python -c "from equity_scout.data.universe_storage import load_instrument_meta; m = load_instrument_meta('/tmp/es_live_smoke.db'); print(len(m), dict(list(m.items())[:3]))"`
Expected: > 0 sectors persisted.

- [ ] **Step 5: Commit**

```bash
git add data/universe_combined.csv data/universe_combined.PROVENANCE.md
git commit -m "feat(universe): global refresh — HK/CN/KR/IN/CA/AU/BR indices (~7.5k tickers)"
```

### Task 11: Docs + spec outcome

**Files:**
- Modify: `README.md` (universe section), `docs/scheduling.md` (prefetch cron + cache-max-age),
  `docs/factors.md` (sector overlay note),
  `docs/superpowers/specs/2026-07-14-global-universe-and-metadata-design.md` (scope-delta note),
  this plan (outcome section).

- [ ] **Step 1: Update the docs** — README universe paragraph (regions + count), scheduling.md
  (new cron line, healing semantics, `--cache-max-age 7` on the Monday run), factors.md
  ("sector source: constituent table → instrument_meta overlay → yfinance backfill").
- [ ] **Step 2: Append an Outcome section to this plan** (what shipped, deviations, open points).
- [ ] **Step 3: Commit**

```bash
git add README.md docs/ && git commit -m "docs: global universe, instrument_meta, prefetch rotation"
```

### Task 12: Final verification (verification-before-completion)

- [ ] **Step 1:** `uv run pytest -q` — all green (expect ~580+).
- [ ] **Step 2:** `uv run ruff check .` — clean.
- [ ] **Step 3:** `cd frontend && npm run build` — clean (only if Task 9 changed anything).
- [ ] **Step 4:** Confirm cron installer output: `bash -n scripts/install_crontab.sh scripts/nightly_prefetch.sh` (syntax check only — actually installing crontab stays a Nico step).
- [ ] **Step 5:** Report: per-source counts, universe size, test count, what Nico still has to do (re-run `./scripts/install_crontab.sh`).

---

## Self-Review (done at write time)

- **Spec coverage:** generic source (T1–T3), 7 configs + refresh wiring + count floors (T2, T4),
  instrument_meta (T5), overlay + harvest incl. cache-hit regression test (T6), scout/scheduled
  wiring (T7), prefetch + cron (T8), dashboards (T9), rollout (T10), docs (T11). Taiwan
  dropped + B3 swap documented as scope deltas (spec's honest-skip rule).
- **Placeholders:** none — every code step carries the actual code.
- **Type consistency:** `rotation_segment(tickers, segments, on)` used identically in T8 script;
  `upsert_instrument_meta(db, sectors, source, updated_at)` identical in T5/T7/T8;
  `harvest_sectors(universe, quotes)` identical in T6/T8; `IndexConfig` fields identical in T1/T2.
