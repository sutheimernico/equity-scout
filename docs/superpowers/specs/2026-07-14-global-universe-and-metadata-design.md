# Global Universe Expansion + Durable Instrument Metadata + Prefetch Warm-up

**Date:** 2026-07-14
**Status:** Approved design (brainstorming session with Nico)
**Owner:** equity-scout

## Goal

1. Extend the screening universe from US/STOXX600/Nikkei225 to true global coverage via the
   major index per remaining region (Nico: "Europa auf jeden Fall, Asien, eigentlich die ganze
   Welt").
2. Fix the `Sector=Unknown` problem structurally: sectors fetched live from yfinance must
   survive across runs instead of being lost on cache hits.
3. Fix the root cause of the rate-limit data loss observed in the 2026-07-14 live run
   (5,275 gated / only 1,043 rankable out of 6,318): the weekly full screen must rank the
   whole universe reliably.

Locked constraints (2026-06-24 decisions, unchanged): free/keyless data only (yfinance,
Wikipedia, official directories); mandatory data-completeness gate stays; public repo — no
bulk third-party-derived data committed beyond index membership snapshots.

## Decisions made in brainstorming

- **Coverage depth:** major indices per region (not full per-country listings, not
  Asia-only). Chosen by Nico 2026-07-14.
- **Scan strategy:** nightly prefetch warm-up + weekly ranking from warm cache (not a
  Monday marathon, not a market-cap floor). Chosen by Nico 2026-07-14.
- **Architecture:** generic config-driven Wikipedia index source + persistent
  `instrument_meta` store + nightly prefetch rotation (approach A). Approved by Nico.

## Root-cause analysis (what is actually broken today)

1. **Cache-hit sector loss:** `yf_provider.quote_from_info_and_history` backfills
   `sector` from yfinance `.info` into the Quote's instrument, but `QuoteCache` persists
   only the metric fields. On a cache hit, `CachedProvider.fetch_quote` rebuilds the Quote
   with the *CSV* instrument (`cache.py:69`), whose sector is still "Unknown". So the
   backfill only ever helps on the exact run that fetched live; every cached run afterwards
   pools thousands of names back into one meaningless "Unknown" sector-ranking group.
2. **Rate-limit data loss:** a single full-universe run exceeds yfinance's tolerated request
   rate; `with_retry` backs off but thousands of names still fail and are gated out as
   "missing price history". The 1-day cache TTL means the next full run re-fetches nearly
   everything and hits the same wall.

## Design

### 1. Generic Wikipedia index source

One new class `WikipediaIndexSource` in `data/constituents.py` (same seam as existing
sources), driven by a per-index config instead of one bespoke class per index:

```python
@dataclass(frozen=True)
class IndexConfig:
    name: str                 # for logs/provenance
    url: str                  # Wikipedia page
    match_columns: set[str]   # identifies the constituents table among page tables
    symbol_column: str
    name_column: str
    sector_column: str | None # None -> sector "Unknown" (meta store fills it later)
    symbol_to_yahoo: Callable[[str], str | None]  # None -> skip row (honest skip)
    region: str
    currency: str
    exchange: str
```

`fetch()` reuses the existing httpx + pandas.read_html + column-set table detection
pattern (`WikipediaStoxx600Source` precedent). Parsing stays a pure function
(`parse_index_records(records, config)`) so every index is fixture-unit-tested without
network. Existing bespoke sources (S&P 500, STOXX 600, Nikkei) stay as they are — no
refactor of working code; the generic source is for the new indices only.

**New index configs (region, expected size, Yahoo mapping):**

| Index | Region | ~Count | Yahoo mapping |
|---|---|---|---|
| Hang Seng Index | HK | 80+ | zero-pad code to 4 digits + `.HK` |
| CSI 300 | CN | 300 | 6-digit code: `6…` → `.SS`, else `.SZ` |
| KOSPI 200 | KR | 200 | 6-digit code + `.KS` |
| NIFTY 50 + NIFTY Next 50 | IN | 100 | NSE symbol + `.NS` |
| S&P/TSX Composite | CA | ~220 | symbol, `.` → `-`, + `.TO` |
| S&P/ASX 200 | AU | 200 | symbol + `.AX` |
| FTSE TWSE Taiwan 50 | TW | 50 | 4-digit code + `.TW` |
| Ibovespa | BR | ~85 | B3 symbol + `.SA` |

Net effect: ~1,200–1,300 new tickers → universe ~7.5k. Region tags use real codes
(HK/CN/KR/IN/CA/AU/TW/BR), extending the dashboard's region grouping.

**Reality check per page (implementation-time):** each Wikipedia page's actual table shape
is verified against a saved HTML fixture. If a page turns out to have no usable
constituents table, that index is dropped with a log note and a spec/plan update — honest
skip over a fragile scrape (house pattern).

**Failure visibility:** `refresh_universe.py` logs a per-source count table and warns when
any source returns fewer rows than a per-index sanity floor (e.g. 50% of expected count).
A source returning 0 must never silently shrink the universe.

### 2. Persistent `instrument_meta` store

New table in the existing SQLite DB (module `data/universe_storage.py`):

```sql
CREATE TABLE IF NOT EXISTS instrument_meta (
  ticker TEXT PRIMARY KEY,
  sector TEXT NOT NULL,
  source TEXT NOT NULL,      -- e.g. "yfinance.info"
  updated_at TEXT NOT NULL   -- ISO date
)
```

- **Write path:** after `fetch_all`, the pipeline upserts `quote.instrument.sector` for
  every instrument whose universe sector was "Unknown" but whose fetched quote carries a
  real sector. Providers stay DB-free; the pipeline owns persistence.
- **Read path:** one pure overlay function `apply_meta_overlay(instruments, meta)` replaces
  `sector == "Unknown"` with the stored sector at universe-load time (run_scout and any
  other pipeline entry point that ranks sector-relative).
- The committed `universe_combined.csv` stays raw source data ("Unknown" where the source
  has none) — no yfinance-derived bulk data enters the public repo; PROVENANCE stays honest.
- This fixes root cause #1: once a sector has been seen live a single time, every later
  run has it, cache hit or not. Sectors change rarely; no TTL in v1 (YAGNI — a re-fetch
  naturally refreshes the row).

### 3. Nightly prefetch warm-up

New script `scripts/run_prefetch.py` (run_* convention):

- **Rotation:** order the universe deterministically by ticker, split into `--segments N`
  (default 6) slices, pick tonight's slice by `day_of_year % N`. No state table needed;
  a missed night (WSL off) is healed automatically on the next pass of the rotation.
- **Fetch:** reuse the existing `CachedProvider` path with `max_age_days = 6` (skip names
  already fresh), low parallelism (`--workers 2`) and the existing `with_retry`
  rate-limit backoff — deliberately gentle, spread over ~6 nights.
- **Side effect:** every successful live fetch also feeds the `instrument_meta` upsert, so
  the sector store fills itself during the first rotation week.
- **Cron:** one new line in `install_crontab.sh` (idempotent, flock like the others),
  nightly 00:45 Mon–Sat — before `nightly_train.sh` (02:30) so they never overlap.

### 4. Weekly screen reads the warm cache

- `run_scout.py` gets `--cache-max-age` (days). The scheduled Monday run
  (`scheduled_run.sh`) passes `7`; the default for ad-hoc runs stays `1`.
- Staleness trade-off, accepted: fundamentals and 6-month momentum computed on data up to
  ~6 days old are fine for a weekly cross-sectional ranking; the intraday copilot/radar
  layer keeps its own fresh fetches for finalists (unchanged).
- Effect: the Monday screen ranks the ~7.5k universe from cache in minutes, live-fetching
  only the misses — root cause #2 solved without a marathon run.

### 5. Unchanged

Gate thresholds, factor definitions, buckets, evidence/copilot layers, dashboards (regions
appear automatically in existing region grouping), LLM thesis, all cron chains except the
one added line.

## Error handling

- Per-source count floor warnings in refresh (see above).
- Prefetch tolerates per-ticker failures: log and continue; the name is retried on the
  next rotation pass. No retry storm.
- `apply_meta_overlay` never overwrites a real source-provided sector, only "Unknown".

## Testing

- Fixture-based unit tests per new index config (saved Wikipedia HTML → expected
  Instruments, including symbol-mapping edge cases: zero-padding, SS/SZ split, `.`→`-`).
- `instrument_meta`: upsert + overlay unit tests; **regression test for the cache-hit
  sector loss** (fetch live once → second cached run must still rank with the real sector).
- Prefetch: rotation determinism (same date → same segment; N nights cover all segments);
  fake-provider test that fresh names are skipped.
- Existing suite (~560 tests) stays green; `ruff` clean.

## Rollout

1. Implement + tests green.
2. `refresh_universe.py` run → new CSV snapshot (~7.5k) + PROVENANCE update, committed.
3. Nico re-runs `./scripts/install_crontab.sh` (also still pending for intraday/nightly
   chains) — machine-level change, stays a Nico step.
4. First prefetch rotation fills cache + sector store over ~6 nights; the second Monday
   screen after merge is the first fully-warm global run.

## Out of scope (explicitly)

- ADR region re-tagging (US-listed ADRs keep region "US" = listing venue; known cosmetic
  limitation, noted in docs).
- ETFs, market-cap/liquidity floors, paid data, higher screen frequency (trivial later via
  cron once warm-cache exists), full per-country listings, UK "EU" tag cleanup.
