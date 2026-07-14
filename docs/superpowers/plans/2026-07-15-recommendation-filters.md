# Recommendation Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filter recommendations by region group, country, and sector — backed by full-ranking persistence per run.

**Architecture:** `run_scores` table (full cross-section per run) fed via a `ranking_sink` pipeline seam; pure `country_of` derivation; `/api/latest` filter params + `/api/filters` options endpoint; a German filter bar in `FunnelView`.

**Tech Stack:** Python/FastAPI/sqlite3, React 19 TS, pytest.

**Spec:** `docs/superpowers/specs/2026-07-15-recommendation-filters-design.md`

---

### Task 1: `country_of` + region groups (pure)

**Files:** Modify `src/equity_scout/universe.py`; Test `tests/test_country_of.py` (create)

- [ ] Tests: US/CA/JP pass through; `EU` + `.PA`→FR, `.DE`→DE, `.L`→GB; `UK` region→GB;
  EU with unknown suffix→"EU"; ticker without suffix + region EU→"EU";
  `REGION_GROUPS` covers exactly {europe, americas, asia, oceania} and every universe
  region code appears in exactly one group.
- [ ] Implement in `universe.py`:

```python
_SUFFIX_COUNTRY = {"PA": "FR", "DE": "DE", "MI": "IT", "MC": "ES", "AS": "NL", "SW": "CH",
                   "ST": "SE", "L": "GB", "BR": "BE", "OL": "NO", "CO": "DK", "HE": "FI",
                   "VI": "AT", "LS": "PT", "IR": "IE"}
REGION_GROUPS = {"europe": {"EU", "UK"}, "americas": {"US", "CA", "BR"},
                 "asia": {"JP", "HK", "CN", "KR", "IN"}, "oceania": {"AU"}}

def country_of(region: str, ticker: str) -> str:
    if region == "UK":
        return "GB"
    if region != "EU":
        return region  # non-EU region tags already are countries (US=listing venue for ADRs)
    _, _, suffix = ticker.rpartition(".")
    return _SUFFIX_COUNTRY.get(suffix, "EU") if suffix else "EU"
```

- [ ] Commit `feat(filters): country derivation + region groups`.

### Task 2: Full-ranking persistence (`ranking_sink` + `run_scores`)

**Files:** Modify `src/equity_scout/pipeline.py`, `src/equity_scout/storage.py`, `scripts/run_scout.py`; Test `tests/test_run_scores.py` (create)

- [ ] Tests: pipeline with `ranking_sink` receives full buckets while RunResult holds
  top-N slices with prefix ranks; `save_run` returns an int id; `save_run_scores` +
  `load_run_scores(db, run_id)` roundtrip incl. country/sector columns; loading for a
  run without rows returns [].
- [ ] `pipeline.py`: add `ranking_sink: Callable[[dict[str, list[Pick]]], None] | None = None`;
  body:

```python
    if ranking_sink is not None:
        full_buckets = assign_buckets(scores, top_n=len(scores))
        ranking_sink(full_buckets)
        buckets = {b: picks[:top_n] for b, picks in full_buckets.items()}
    else:
        buckets = assign_buckets(scores, top_n=top_n)
```

- [ ] `storage.py`: `save_run` returns `cur.lastrowid`; new `init` DDL for `run_scores`
  (+ index); `save_run_scores(db_path, run_id, buckets)` writes one row per pick with
  `country_of(...)`; `load_run_scores(db_path, run_id, bucket=None, region_codes=None,
  country=None, sector=None, limit=None)` returns dicts ordered by bucket+rank.
- [ ] `run_scout.py`: collect sink payload, `run_id = save_run(...)`, then
  `save_run_scores(args.db, run_id, full)`.
- [ ] Full suite green; commit `feat(filters): persist full per-run ranking (run_scores)`.

### Task 3: API filter params + options endpoint

**Files:** Modify `src/equity_scout/api.py`; Test extend the existing API test module (check `ls tests/ | grep -i api`).

- [ ] Tests: `/api/latest?sector=Technology` returns only matching picks, re-ranked,
  payload has `filters` echo + `filter_matches`; unknown filter values → empty buckets +
  `filter_matches: 0`; run without `run_scores` rows → `filter_unavailable: true`;
  `/api/filters` lists countries/sectors with counts; no params → payload identical to
  today (regression).
- [ ] Implement: `latest(region: str | None = None, country: str | None = None,
  sector: str | None = None)`; region resolves group names via `REGION_GROUPS` else
  treated as a single code; filtered path queries `run_scores` for the latest run id,
  groups by bucket, takes 10, re-ranks 1..n. `/api/filters` = fixed groups + SELECT
  DISTINCT counts.
- [ ] Full suite green; commit `feat(api): region/country/sector filters + options endpoint`.

### Task 4: Frontend filter bar

**Files:** Modify `frontend/src/api.ts`, `frontend/src/components/FunnelView.tsx` (+ a small `FilterBar` component if FunnelView grows unwieldy).

- [ ] `api.ts`: `fetchLatest(filters?)` appends query params; `fetchFilters()` typed.
- [ ] `FunnelView`: three selects (Alle Regionen/Europa/Amerika/Asien/Ozeanien; Alle
  Länder; Alle Sektoren — options with counts from `/api/filters`), reset button, result
  count line, "Keine Treffer für diesen Filter" for empty buckets. German UI text,
  existing token/design system (match surrounding components).
- [ ] `cd frontend && npm run typecheck && npm run build` green (check package.json for
  exact script names); commit `feat(frontend): region/country/sector filter bar`.

### Task 5: Backfill + gate + docs

- [ ] Backfill the CURRENT latest run so the filters work immediately (one-off script or
  inline python): recompute via cached quotes is NOT needed — re-run
  `scripts/run_scout.py --provider yfinance --cache-max-age 7 ...` (warm cache, minutes)
  which now persists `run_scores`. Verify `/api/filters` returns real options.
- [ ] `uv run pytest -p no:warnings` + `ruff` + FE build green.
- [ ] README (filter feature), spec/plan outcome sections; commit docs.

---

## Outcome (2026-07-15, executed same session)

**Shipped** (commits `2b838c9..5ff2349` + backfill): all 5 tasks. `country_of` + REGION_GROUPS,
`ranking_sink` → `run_scores` (6,117 rows verified on the live run), `/api/latest` filter
params + `/api/filters` facets (23 API tests), German filter bar in FunnelView (server-side,
replaces the old top-30-only client filter; typecheck + build green). Backfill scout ran —
facets live: US 4465, CN 294, JP 223, CA 203, AU 190, KR 166, GB 100, IN 99; sectors led by
Industrials/Financial Services/Technology. Sample "JP + Technology" → 8035.T, 6758.T.

**Notes:** sector taxonomy stays a heterogeneous mix (yfinance GICS + Nikkei headings + B3
industries) as speced — "Wasser" exists only where a source names it that way. 453 names
still sector-"Unknown" (shrinks with the nightly prefetch rotation).
