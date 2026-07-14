# Recommendation Filters: Region Group / Country / Sector

**Date:** 2026-07-15 (session of 2026-07-14, past midnight)
**Status:** Approved (Nico verbal + standing blanket go)

## Goal (Nico's words, condensed)

Filter the recommendations by region (coarse: EU, America, Asia), by individual country,
and by sector (technology, energy, oil, water, …).

## Design

### Full-ranking persistence (prerequisite)

Runs currently persist only the top-N picks per bucket (~30 rows) — filtering that is
pointless ("Energie + Japan" would almost always be empty). New: every run also persists
its FULL cross-sectional ranking (~6k rows) in a `run_scores` table:

```sql
CREATE TABLE IF NOT EXISTS run_scores (
  run_id INTEGER NOT NULL, bucket TEXT NOT NULL, rank INTEGER NOT NULL,
  ticker TEXT NOT NULL, name TEXT NOT NULL, region TEXT NOT NULL,
  country TEXT NOT NULL, sector TEXT NOT NULL,
  composite REAL NOT NULL, breakdown TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_scores_run ON run_scores (run_id);
```

- `run_pipeline` gains `ranking_sink` (same seam pattern as `sector_sink`): when set, the
  full buckets (`assign_buckets` with `top_n=len(scores)`) go to the sink and the
  RunResult keeps the sliced top-N (ranks are a prefix, so slicing preserves them). News
  and LLM theses attach to the sliced picks only — cost unchanged.
- `save_run` returns the new run id (`lastrowid`); `run_scout` writes the sink payload
  via `save_run_scores(db, run_id, full_buckets)` after `save_run`.
- Old runs have no `run_scores` rows → the API reports filters as unavailable for them
  (honest hint) instead of silently showing unfiltered data.

### Country derivation (no Instrument/CSV change)

Pure function `country_of(region, ticker) -> str`:
- Region codes that already are countries pass through: US, CA, BR, JP, CN, KR, IN, AU, HK.
- `EU`/`UK` resolve via the Yahoo exchange suffix: `.PA`→FR, `.DE`→DE, `.MI`→IT, `.MC`→ES,
  `.AS`→NL, `.SW`→CH, `.ST`→SE, `.L`→GB, `.BR`→BE, `.OL`→NO, `.CO`→DK, `.HE`→FI, `.VI`→AT,
  `.LS`→PT, `.IR`→IE; unmappable → the region code itself (honest fallback).
- Known limitation (documented): US-listed ADRs count as US (listing venue), same as the
  region tag.

Region groups (fixed mapping, coarse filter): `europe` = {EU, UK}, `americas` = {US, CA,
BR}, `asia` = {JP, HK, CN, KR, IN}, `oceania` = {AU}.

### API

- `GET /api/latest?region=<group|code>&country=<code>&sector=<name>` — with any filter
  param present, buckets are rebuilt from the latest run's `run_scores` (filters ANDed,
  top 10 per bucket, re-ranked 1..n within the filtered set), payload carries
  `"filters"` (echo) and `"filter_matches"` (total matching rows). Without params the
  endpoint behaves exactly as today. Sector matching is case-insensitive exact.
- `GET /api/filters` — options for the dropdowns from the latest run's `run_scores`:
  region groups (fixed), countries and sectors as `{value, count}` sorted by count.

### Frontend

Filter bar on the screener view (`FunnelView`): three selects — Region (Alle Regionen /
Europa / Amerika / Asien / Ozeanien), Land (Alle Länder / from `/api/filters`), Sektor
(Alle Sektoren / from `/api/filters`), German labels, options show counts. Any change
refetches `/api/latest` with params. Active filters show a result count + reset button;
an empty filtered bucket says "Keine Treffer für diesen Filter" instead of hiding.

### Out of scope

Filtering the Telegram digest (dashboard-only feature), free-text sector search, sector
taxonomy normalization across sources (values stay as delivered: yfinance/GICS/ICB mix),
re-running factor percentiles within the filtered subset (ranks stay global — filtering
selects from the global ranking, it does not re-score).
