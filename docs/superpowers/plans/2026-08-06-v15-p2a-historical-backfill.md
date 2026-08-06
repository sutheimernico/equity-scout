# Vision v15 — P2a: Historical Catalyst Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the future catalyst/insider/congress lanes (P2) and the entry-model feature work (P3) 10–20 years of measured priors: ingest historical catalyst events point-in-time, resolve their forward returns vs SPY, and report base rates + conditional splits — with survivorship gaps counted, never hidden.

**Requirements doc:** `docs/superpowers/specs/2026-08-05-vision-v15-two-depots-evidence-learning.md` section "Proposed P2a" (verified sources, design constraints, honesty limits). This plan implements exactly that scope.

**Architecture (locked):**
- New table `historical_events` in `equity_scout.db` via a new `src/equity_scout/evidence/historical_storage.py`, following the `evidence/storage.py` contract (INSERT OR IGNORE dedupe on `UNIQUE(source, ticker, event_key)`, injected `now`, no wall clock in library code). Forward returns live as nullable columns on the event row (`r_1w, r_1m, r_3m, r_6m, r_12m`, plus `resolved_at`, `unresolvable`, `unresolvable_reason`) — history needs no predict-then-resolve ledger, every window has already elapsed; resolution is deterministic and idempotent.
- Three collectors, one file each, all with the `http_get: Callable[[str], str] | None = None` seam exactly like `evidence/congress.py:47-52`: `evidence/backfill_congress.py` (kadoa per-filer JSONs), `evidence/backfill_form4.py` (SEC quarterly insider TSV ZIPs — binary, so this one takes `http_get_bytes`), `evidence/backfill_statements.py` (Trump Twitter Archive CSV + Truth Social mirror CSV, classified via the existing `voices.classify_mention` — deterministic, no LLM).
- Study aggregation in `src/equity_scout/evidence/historical_study.py`: base rates per class/person + conditional splits on deterministic features only, time-split (fit ≤2021-12-31, validate 2022→), min-N per cell, `{"measurable": False, "reason": ...}` honesty pattern copied from `event_reactions.aggregate_reactions` (`event_reactions.py:263-317`).
- Scripts: `scripts/run_history_backfill.py` (per-source, resumable cursor in `app_state`, dry-run default + `--apply` per the `fix_*` convention), `scripts/run_history_resolve.py` (batch forward returns, own snapshot `data/prices/history_panel.csv`), `scripts/run_history_report.py` (prints + writes `docs/research/history-study-report.json`). NOT wired into daily/nightly chains — this is a manually-run, resumable batch job.
- T0 is ALWAYS the knowable date: filing date (congress/form4, per `person_track.py:43` convention), post timestamp (statements). `form4`-style PIT guard: discard and count rows where filing < transaction is violated in reverse.
- Form 4 granularity: **cluster events only** (≥3 distinct insiders buying the same ticker within a 10-trading-day window; `MIN_INSIDERS` imported from `evidence/aggregate.py:40`) — matches the P2 insider-cluster lane signal and keeps volume sane. Single large purchases: backlog, not this plan.

**Tech Stack:** Python 3 (uv), pandas, sqlite3, httpx (per-collector, as in congress.py), yfinance via `equity_scout.data.etf_panel.load_price_history` + `data/fetch.with_retry`. Gate: `uv run pytest -q` green + `uv run ruff check .` clean before every commit.

**Controller decisions during execution (binding for later tasks):**
1. *Resolution semantics (resolves a Task-1-vs-Task-5 wording conflict found in review):* `mark_resolved` is **per-column one-way** — each `r_*` column is individually write-once; `resolved_at` is set only when all five horizons are non-NULL, so young events stay in `unresolved_events` (which also returns the `r_*` columns) until every window has elapsed. "Second call refused" applies per column, not per row.
2. *`person` convention for cluster events (Task 3):* Form-4 cluster events have no single person — store `person = ""` (insider names live in `details`). Task 6 aggregates per person only where `person != ""`.
3. *Query hygiene (Task 6):* `resolved_at` is also set by `mark_unresolvable` — never read `resolved_at IS NOT NULL` alone as "has usable r_* data"; always add `AND unresolvable = 0`.
4. *Aggregation semantics (Task 6, binding):* under per-column resolution, `unresolvable = 1` rows CAN carry measured `r_*` values (e.g. delisted after 1 month: real `r_1w`/`r_1m`, then `no_price_history` for the rest). Task 6 therefore aggregates each horizon over `r_X IS NOT NULL` — dropping `unresolvable` rows from base rates would discard exactly the delisted names the survivorship disclaimer exists for. `unresolvable` feeds only the coverage/survivorship counters; `resolved_at` feeds no published number at all.
5. *Congress seed population (Task 2 review finding):* the capped `trades.json` carries only 95 of the mirror's 440 filers (`public/data/filers.json`) — seeding a 14-year study from recent traders is survivorship bias. `backfill_congress` seeds from the full filer index, falling back to trades.json (counted) if the index is unreachable.
6. *Executive filers under source="congress" (Task 6):* OGE executive-branch filers (president, cabinet) are included; `details.chamber` carries `chamber or branch`. Task 6 must split by chamber/branch and the report wording is "congress & executive filers", not "congress" alone.
7. *Keep-rule mirroring (backlog, NOT this plan):* the purchase keep-rules now exist 3× (congress.py, person_track.py, backfill_congress.py) with already-divergent dedupe keys. Extracting a shared kept-purchase-rows generator is a post-P2a refactor candidate — deliberately not done here (plan mandated mirroring; scope discipline).

**Coordination:** A parallel autopilot session owns `st_session.py`, `alpaca_*.py`, `scripts/run_shortterm.py`, `PLAN.md`, `frontend/` — this plan touches NONE of those. Commit only explicit paths (`git add <paths>`, never `-A`); working tree currently carries that session's uncommitted frontend changes. Do NOT edit PLAN.md.

**Hard constraints (inherited):** free data only; `EDGAR_USER_AGENT` for anything sec.gov (degrade to `STATUS_UNCONFIGURED` like `form4.py:250-259` when unset); GDELT is OUT (BigQuery = cloud, conflicts with the private hard line — Needs Nico, see spec); LLM never scores/ranks anything; determinism in tests (canned payloads via injected closures, no network).

---

### Task 1: `historical_storage.py` — table + record + read-back

**Files:** Create `src/equity_scout/evidence/historical_storage.py`, `tests/test_historical_storage.py`.

- [x] **Step 1:** Failing tests: `init_historical_db` creates `historical_events(id, source, person, ticker, event_key, t0, details_json, created_at, r_1w REAL, r_1m REAL, r_3m REAL, r_6m REAL, r_12m REAL, resolved_at TEXT, unresolvable INTEGER DEFAULT 0, unresolvable_reason TEXT, UNIQUE(source, ticker, event_key))`; `record_historical_events(db, events, *, now)` inserts with INSERT OR IGNORE and returns only new rows (copy the `storage.py:34-61` contract); `unresolved_events(db, limit=None)` returns rows with `resolved_at IS NULL AND unresolvable = 0`; `mark_resolved(db, event_id, returns: dict, *, now)` writes the r_* columns once (second call refused, first stands — same one-way convention as `evidence/ledger.py`); `mark_unresolvable(db, event_id, reason, *, now)`.
- [x] **Step 2:** Run tests → fail. Implement. Run module tests → pass.
- [x] **Step 3:** Full gate; commit `feat(history): historical_events storage with one-way resolution`. *(Done: 69c3d99 + c969c70 + 3dbd09a, then review-driven 7bac472 per-column resolution + central db.connect, 6c3c06e refuse-whole test. Two-stage review passed.)*

### Task 2: Congress backfill collector (kadoa per-filer JSONs, 2012→)

**Files:** Create `src/equity_scout/evidence/backfill_congress.py`, `tests/test_backfill_congress.py`.

- [x] **Step 1:** Failing tests with canned JSON payloads (reuse shapes from `tests/test_evidence_congress.py`): `filer_ids_from_trades(trades_json_text)` extracts the distinct filer ids from the capped `trades.json`; `events_from_filer_payload(payload, *, person)` converts one filer history into `HistoricalEvent`s — purchases only, resolvable ticker only, T0 = filing date, event_key `f"{filer_id}-{transaction_date}-purchase"` (same collapse rule as `congress.py:104`), details carry amount-band/chamber/committee when present. NO filing-age bound (backfill wants the history — mirror `person_track.calls_from_filer_payload`, `person_track.py:65-109`, including its keep-rules).
- [x] **Step 2:** `backfill_congress(db, *, now, http_get=None, filer_ids=None)` — fetch `FILER_URL_TEMPLATE` per filer (reuse the constant from `congress.py:34-37`), record via Task 1, return counts `{filers, events_new, events_seen}`. Broken-feed path: one failing filer is counted and skipped, never aborts the run (closure raising OSError, as in `test_evidence_congress.py:67-76`).
- [x] **Step 3:** Full gate; commit `feat(history): congress backfill from kadoa filer histories`. *(Done: f13d04a + review-driven cf7e944 — full 440-filer index seed per Decision 5, earliest-t0 collapse, counted failures/skips — + 8062a6b loud empty-index fallback and rows denominator. 27 module tests. Two-stage review passed.)*

### Task 3: Form 4 bulk collector (SEC quarterly TSVs, 2006→) — VERIFY FORMAT FIRST

**Files:** Create `src/equity_scout/evidence/backfill_form4.py`, `tests/test_backfill_form4.py`.

- [ ] **Step 0 (verify before coding):** With the configured `EDGAR_USER_AGENT`, download ONE quarter ZIP from the SEC "Insider Transactions Data Sets" page (e.g. 2024q1) to the scratchpad, inspect actual member names + columns (expected per secondary sources: `SUBMISSION.tsv` with ACCESSION_NUMBER/FILING_DATE/ISSUERTRADINGSYMBOL, `NONDERIV_TRANS.tsv` with TRANS_CODE/TRANS_DATE/RPTOWNERNAME-equivalents — CONFIRM, do not trust this list). Record the verified layout as a comment block in the module and build the test fixture TSVs from the real column names. If the layout differs, adapt here, not downstream.
- [ ] **Step 1:** Failing tests with two-file fixture ZIPs (bytes in-memory): `purchases_from_quarter_zip(zip_bytes)` yields open-market purchases (TRANS_CODE == "P") joined to issuer symbol + owner name + FILING date (PIT guard: discard filing < transaction, count as `discarded_pit` like `form4.py:299-310`); `cluster_events(purchases, *, window_trading_days=10, min_insiders=MIN_INSIDERS)` groups per ticker, emits one `HistoricalEvent` per cluster (T0 = LAST filing date of the cluster — only then were all ≥3 buys knowable), event_key `f"{ticker}-{t0}-cluster{n_insiders}"`, details = insider names + total txn value band.
- [ ] **Step 2:** `backfill_form4_quarter(db, quarter, *, now, http_get_bytes=None)` + quarter cursor in `app_state` (`state_storage.py` KV, key `history_form4_cursor`) so the multi-year run is resumable one quarter at a time. Unconfigured UA → `STATUS_UNCONFIGURED`-style early return, never a fake.
- [ ] **Step 3:** Full gate; commit `feat(history): form4 cluster backfill from SEC quarterly data sets`.

### Task 4: Statements collector (Trump archives, 2009→)

**Files:** Create `src/equity_scout/evidence/backfill_statements.py`, `tests/test_backfill_statements.py`.

- [ ] **Step 1:** Failing tests with canned CSV rows: `events_from_statement_rows(rows, universe, aliases, *, person="Donald Trump")` runs each text through `voices.classify_mention` (`voices.py:365-386` — name-before-verb, closed direction lists, `resolve_ticker` never guesses); keep only unambiguous (ticker, direction) hits; T0 = post timestamp; event_key `f"{person_slug}-{post_id}"`; details carry platform, direction, matched phrase. Ambiguous/no-ticker rows are counted, not stored.
- [ ] **Step 2:** `backfill_statements(db, *, now, http_get=None)` fetching the two archive CSVs (Twitter archive mirror + stiles/trump-truth-social-archive raw CSV — URLs as module constants with a comment that both are best-effort community mirrors; a dead mirror degrades to a counted skip). Coverage gap 01/2021–2022 (platform ban) documented in the module docstring and surfaced in the counts.
- [ ] **Step 3:** Full gate; commit `feat(history): statement backfill via deterministic voices classifier`.

### Task 5: Resolution runner (forward returns, survivorship counted)

**Files:** Create `scripts/run_history_resolve.py`, `tests/test_run_history_resolve.py`.

- [ ] **Step 1:** Failing tests with synthetic panels (plain DataFrames, as in `test_person_track.py:70-88`): `resolve_batch(events, panel, *, now)` computes `relative_forward_return` (import from `ml/entry_eval.py` — do NOT reimplement) at horizons `{"r_1w": 5, "r_1m": 21, "r_3m": 63, "r_6m": 126, "r_12m": 252}` trading days from the first panel date ≥ t0; panel-starts-after-t0 → unresolvable `panel_gap` (the Wave-1 shifted-window lesson); ticker missing entirely → unresolvable `no_price_history` (the survivorship bucket); windows that extend beyond the panel end (young events) stay open, partial horizons are written only for the elapsed windows.
- [ ] **Step 2:** Script: batch unresolved events' tickers in chunks of ≤50 through `load_price_history(..., snapshot="data/prices/history_panel.csv")` with `with_retry` semantics; `--limit` for incremental runs; per-run summary printed in the Wave-1 style ("Aufgelöst: X, unresolvable: Y (davon no_price_history: Z), offen: W"). Dry-run default, `--apply` writes.
- [ ] **Step 3:** Full gate; commit `feat(history): batch forward-return resolution with counted survivorship gaps`.

### Task 6: Study aggregation + report

**Files:** Create `src/equity_scout/evidence/historical_study.py`, `scripts/run_history_report.py`, `tests/test_historical_study.py`.

- [ ] **Step 1:** Failing tests: `aggregate_history(db, *, split_date="2021-12-31", min_cell_n=30)` returns per source-class (congress / insider_cluster / statement) and per person: `{n, coverage (resolved/total incl. unresolvable-by-reason), hit_rate and mean_relative_return per horizon, fit vs validate split}`; conditional splits ONLY on deterministic features present in details (amount band, chamber, cluster size, direction), each cell reported with its n and refused below `min_cell_n` (`{"measurable": False, "reason": "n<30"}`); NO cell without both fit AND validate coverage may claim an edge.
- [ ] **Step 2:** `run_history_report.py` prints the aggregate and writes `docs/research/history-study-report.json` (overwrite-is-fine derived state, like `person_storage`). The report header carries the survivorship disclaimer verbatim from the spec.
- [ ] **Step 3:** Full gate; commit `feat(history): base-rate study with time-split validation and honest cells`.

### Task 7: Backfill runner + first real run

**Files:** Create `scripts/run_history_backfill.py`.

- [ ] **Step 1:** Script with `--source {congress,form4,statements}` + `--apply` (dry-run default prints would-insert counts), threading `now` once from `main()`, per-source cursors. `main() -> int`, `sys.exit(main())`, docstring-as-description — the repo script template.
- [ ] **Step 2 (live, requires network):** Run congress + statements fully, form4 for the two most recent quarters (full 2006→ run is a multi-hour resumable job — kick it off, note progress in the Outcome). Then `run_history_resolve.py --apply` in batches, then `run_history_report.py`.
- [ ] **Step 3:** Full gate; commit; fill this plan's Outcome section with: row counts per source, coverage/survivorship percentages, and the first base-rate table. **The report's numbers go to Nico for the P2 lane-design decisions — they are evidence, not an automatic go.**

---

## Expected proof

After Task 7, `docs/research/history-study-report.json` exists with n, coverage, and per-horizon base rates per class — including an explicit `no_price_history` count per class (the survivorship bucket). If congress purchases 2012→ show no validate-window edge in any honest cell, that is a RESULT (it kills a lane cheaply before it wastes 60 days of paper track), not a failure of this plan.

## Outcome

(filled after execution)
