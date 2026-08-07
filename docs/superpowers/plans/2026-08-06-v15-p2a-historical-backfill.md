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
7. *Form4 source string (Task 3/6):* cluster events use the existing `SOURCE_INSIDER = "insider"` from `evidence/base.py` — the plan's class name "insider_cluster" is report wording only. Task 6 queries `source = 'insider'` and labels the class "insider clusters". Also: the SEC publishes each quarterly set weeks after quarter end — a `fetch_failed` on the newest candidate quarter is NORMAL in Task 7, not an error (cursor holds, retried next run). 4/A amendments are excluded by design, mirroring form4.py.
8. *Form4 cluster event_key (Task 3 review, overrides the Step-1 literal):* `f"{ticker}-{t0}-{first_transaction_date}-cluster{n}"` — the plan's original key collided for same-day batch late-filings (measured: 8/338 clusters silently dropped on 2006q1). Quarter-boundary clusters are structurally invisible (per-quarter files); `boundary_candidates` counter + filing-lag metrics in details keep that honest for Task 6/7.
9. *Statements strict matching (Task 4 review — CRITICAL):* the full-corpus run (78,728 rows) produced 44 events, ALL fabricated attributions (first-word/caps-token ticker channels were calibrated for short financial headlines, not long political posts against a 7,499-name global universe). Ruling: statements use a strict full-name-only resolve channel (additive `strict` parameter in voices.resolve_ticker, default False = live behavior unchanged), retweets are filtered (counted, an RT is not the person's OWN statement), exact-text repeats deduped. If the strict run yields ~0 events, that IS the study result for this class. Task 7 must not `--apply` statements before this landed. **Final burial (ratified after re-review):** the strict run measured 10 surviving events, all manually verified false (0 genuine calls, defended against strict's 32.5% single-token blind spot via the 4 affected candidates). The 10 are NEVER written to historical_events (irreversible store; min_cell_n is a statistical control, not a known-false-data control). Enforcement: Task 7's runner excludes `statements` from apply-able sources (dry-run only, reason in help text); Task 6/7's report emits the negative result explicitly (`statement: {n: 0, corpus_rows: 78728, candidates: 132, raw_events: 10, genuine: 0, published: false}`) so "measured, found nothing" is distinguishable from "never ran".
10. *t0 column contract (all collectors):* `t0` is a plain ISO DATE (`published[:10]`); full timestamps go to `details["published"]`. Congress/form4 already comply; statements normalizes.
11. *Stale-tail masking (Task 5 review — Critical):* the panel loader's `.ffill()` freezes delisted tickers' prices to the panel end, fabricating full five-horizon "measurements" for dead names. Fix: additive `mask_stale_tail` param in `etf_panel` (default = live behavior unchanged), resolver-only; dead tickers keep measured horizons and bury the rest as `no_price_history` (Decision 4's partially-measured case). Throttled all-NaN columns are guarded by a chunk threshold + single-ticker recheck before any burial. **Needs Nico (recommendation, not done):** applying the mask to the live person_track/person_scores path would make those numbers more honest too, but shifts live values. Methodology note for Task 6: horizons count panel rows, not exchange sessions; entry = close of first panel date ≥ t0.
12. *Keep-rule mirroring (backlog, NOT this plan):* the purchase keep-rules now exist 3× (congress.py, person_track.py, backfill_congress.py) with already-divergent dedupe keys. Extracting a shared kept-purchase-rows generator is a post-P2a refactor candidate — deliberately not done here (plan mandated mirroring; scope discipline).

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

- [x] **Step 0 (verify before coding):** With the configured `EDGAR_USER_AGENT`, download ONE quarter ZIP from the SEC "Insider Transactions Data Sets" page (e.g. 2024q1) to the scratchpad, inspect actual member names + columns (expected per secondary sources: `SUBMISSION.tsv` with ACCESSION_NUMBER/FILING_DATE/ISSUERTRADINGSYMBOL, `NONDERIV_TRANS.tsv` with TRANS_CODE/TRANS_DATE/RPTOWNERNAME-equivalents — CONFIRM, do not trust this list). Record the verified layout as a comment block in the module and build the test fixture TSVs from the real column names. If the layout differs, adapt here, not downstream.
- [x] **Step 1:** Failing tests with two-file fixture ZIPs (bytes in-memory): `purchases_from_quarter_zip(zip_bytes)` yields open-market purchases (TRANS_CODE == "P") joined to issuer symbol + owner name + FILING date (PIT guard: discard filing < transaction, count as `discarded_pit` like `form4.py:299-310`); `cluster_events(purchases, *, window_trading_days=10, min_insiders=MIN_INSIDERS)` groups per ticker, emits one `HistoricalEvent` per cluster (T0 = LAST filing date of the cluster — only then were all ≥3 buys knowable), event_key `f"{ticker}-{t0}-cluster{n_insiders}"`, details = insider names + total txn value band.
- [x] **Step 2:** `backfill_form4_quarter(db, quarter, *, now, http_get_bytes=None)` + quarter cursor in `app_state` (`state_storage.py` KV, key `history_form4_cursor`) so the multi-year run is resumable one quarter at a time. Unconfigured UA → `STATUS_UNCONFIGURED`-style early return, never a fake.
- [x] **Step 3:** Full gate; commit `feat(history): form4 cluster backfill from SEC quarterly data sets`. *(Done: 2274ff9 — live-verified layout incl. 3-way join, DD-MON-YYYY, group filings — + review-driven de121e3 collision-free keys/TSV hardening/lag metrics + 9c6efbd cross-issuer CIK visibility. 50 module tests, verified E2E on real 2006q1 (339 clusters) and 2024q1 (179). Two-stage review passed. mixed_issuer clusters: kept in base rates, surfaced in Task-6 coverage.)*

### Task 4: Statements collector (Trump archives, 2009→)

**Files:** Create `src/equity_scout/evidence/backfill_statements.py`, `tests/test_backfill_statements.py`.

- [x] **Step 1:** Failing tests with canned CSV rows: `events_from_statement_rows(rows, universe, aliases, *, person="Donald Trump")` runs each text through `voices.classify_mention` (`voices.py:365-386` — name-before-verb, closed direction lists, `resolve_ticker` never guesses); keep only unambiguous (ticker, direction) hits; T0 = post timestamp; event_key `f"{person_slug}-{post_id}"`; details carry platform, direction, matched phrase. Ambiguous/no-ticker rows are counted, not stored.
- [x] **Step 2:** `backfill_statements(db, *, now, http_get=None)` fetching the two archive CSVs (Twitter archive mirror + stiles/trump-truth-social-archive raw CSV — URLs as module constants with a comment that both are best-effort community mirrors; a dead mirror degrades to a counted skip). Coverage gap 01/2021–2022 (platform ban) documented in the module docstring and surfaced in the counts.
- [x] **Step 3:** Full gate; commit `feat(history): statement backfill via deterministic voices classifier`. *(Done: 04e0661 + review-driven strict matching/RT filter/dedupe (landed inside 6aacfe0 via a commit collision with the parallel session — content verified) + 3196c46 qualified zero-claim. 52 module tests + 6 strict-mode voices tests. STUDY RESULT per Decision 9: class is dead — 78,728 rows → 10 events, all verified false, never written. Two-stage review passed.)*

### Task 5: Resolution runner (forward returns, survivorship counted)

**Files:** Create `scripts/run_history_resolve.py`, `tests/test_run_history_resolve.py`.

- [x] **Step 1:** Failing tests with synthetic panels (plain DataFrames, as in `test_person_track.py:70-88`): `resolve_batch(events, panel, *, now)` computes `relative_forward_return` (import from `ml/entry_eval.py` — do NOT reimplement) at horizons `{"r_1w": 5, "r_1m": 21, "r_3m": 63, "r_6m": 126, "r_12m": 252}` trading days from the first panel date ≥ t0; panel-starts-after-t0 → unresolvable `panel_gap` (the Wave-1 shifted-window lesson); ticker missing entirely → unresolvable `no_price_history` (the survivorship bucket); windows that extend beyond the panel end (young events) stay open, partial horizons are written only for the elapsed windows.
- [x] **Step 2:** Script: batch unresolved events' tickers in chunks of ≤50 through `load_price_history(..., snapshot="data/prices/history_panel.csv")` with `with_retry` semantics; `--limit` for incremental runs; per-run summary printed in the Wave-1 style ("Aufgelöst: X, unresolvable: Y (davon no_price_history: Z), offen: W"). Dry-run default, `--apply` writes.
- [x] **Step 3:** Full gate; commit `feat(history): batch forward-return resolution with counted survivorship gaps`. *(Done: ee2c768 + review-driven aa8dd1f — Critical fix: additive mask_stale_tail against ffill-fabricated returns for delisted names, resolved_then_buried bucket = Decision 4's case, throttle guard + single-ticker recheck — + 4a61e89 halt-safe 21-session margin, recheck cap, bucket symmetry. 42 module tests, gate 1651. Two-stage review passed; reviewer released Task 7 --apply.)*

### Task 6: Study aggregation + report

**Files:** Create `src/equity_scout/evidence/historical_study.py`, `scripts/run_history_report.py`, `tests/test_historical_study.py`.

- [x] **Step 1:** Failing tests: `aggregate_history(db, *, split_date="2021-12-31", min_cell_n=30)` returns per source-class (congress / insider_cluster / statement) and per person: `{n, coverage (resolved/total incl. unresolvable-by-reason), hit_rate and mean_relative_return per horizon, fit vs validate split}`; conditional splits ONLY on deterministic features present in details (amount band, chamber, cluster size, direction), each cell reported with its n and refused below `min_cell_n` (`{"measurable": False, "reason": "n<30"}`); NO cell without both fit AND validate coverage may claim an edge.
- [x] **Step 2:** `run_history_report.py` prints the aggregate and writes `docs/research/history-study-report.json` (overwrite-is-fine derived state, like `person_storage`). The report header carries the survivorship disclaimer verbatim from the spec.
- [x] **Step 3:** Full gate; commit `feat(history): base-rate study with time-split validation and honest cells`. *(Done: 48e2a8c + review-driven 12773c0 — edge claims renamed to direction-agreement-only after the reviewer measured ~50% null pass-rate (9/9 cells claimed on pure noise), multiplicity made numeric (n_gated_cells, expected_spurious_at_50pct in dict AND summary lead), stdev/stderr, per-side hit rates, claims index. 41 module tests, gate 1692. Two-stage review passed.)*

### Task 7: Backfill runner + first real run

**Files:** Create `scripts/run_history_backfill.py`.

- [x] **Step 1:** Script with `--source {congress,form4,statements}` + `--apply` (dry-run default prints would-insert counts), threading `now` once from `main()`, per-source cursors. `main() -> int`, `sys.exit(main())`, docstring-as-description — the repo script template. *(Done: a52be5b, 26 module tests, gate 1718.)*
- [x] **Step 2 (live, requires network):** Run congress + statements fully, form4 for the two most recent quarters (full 2006→ run is a multi-hour resumable job — kick it off, note progress in the Outcome). Then `run_history_resolve.py --apply` in batches, then `run_history_report.py`. *(Done — form4 ran to completion, not just two quarters. Resolution is the blocker, see Outcome P0.)*
- [x] **Step 3:** Full gate; commit; fill this plan's Outcome section with: row counts per source, coverage/survivorship percentages, and the first base-rate table. **The report's numbers go to Nico for the P2 lane-design decisions — they are evidence, not an automatic go.**

---

## Expected proof

After Task 7, `docs/research/history-study-report.json` exists with n, coverage, and per-horizon base rates per class — including an explicit `no_price_history` count per class (the survivorship bucket). If congress purchases 2012→ show no validate-window edge in any honest cell, that is a RESULT (it kills a lane cheaply before it wastes 60 days of paper track), not a failure of this plan.

## Outcome

**Status: ingestion COMPLETE, resolution BLOCKED at 2.9% coverage.** All three collectors ran
live against their real sources and the store now holds 50,955 point-in-time events spanning
2006-01-03 → 2026-08-05. The forward-return resolver, however, converged after two full passes
with only 2.9% of those events measured and **96.7% never evaluated at all** — not buried, not
counted as survivorship, simply never looked at. The cause is a single Task-5 constant and is
written up as P0 below. **The
base-rate table further down is therefore NOT decision-grade for the P2 lane design.**

### Row counts per source (live runs, 2026-08-07)

| Source | Ingested | Detail |
|---|---|---|
| congress & executive filers | **23,274** events | 440 filers from the full index, 0 failed, 65,859 transaction rows read; discarded: no ticker 7,925, not a stock purchase 2,137, duplicate 1,575, malformed 0, no date 0 |
| insider clusters (form4) | **27,681** events | **82/82 quarters ok, 2006q1 → 2026q2 — the full 2006→ walk finished** (~7 min, not the estimated multi-hour job); 0 event_key collisions, 3,564 quarter-boundary candidates (structurally invisible, Decision 8), 61 mixed-issuer clusters. Cursor `history_form4_cursor = 2026q2`, i.e. caught up. No `fetch_failed` on the newest quarter — Decision 7's publication lag did not materialise this run |
| statements | **0** events (dry-run only) | Decision 9 enforced by the runner: 78,728 corpus rows (twitter 54,324 + truth_social 24,404) → 132 candidates → 10 raw events → **0 genuine**, `published: false`. Re-measured live, never written. Coverage gap confirmed: Twitter ends 2021-01-08, Truth Social starts 2022-02-14 |

`--apply --source statements` exits 2 without touching the database, with the burial reason in
both the refusal message and `--help`.

### Delisting probe (Decision 11 + the Task-5 review flag) — PASSED

15 known delisted/acquired tickers with t0 set 6–14 months before their delisting, plus 2 live
CONTROLS and 25 live FILLER names (so the dead share per chunk stays under the resolver's 30%
threshold), in a throwaway scratchpad DB. Result:

* **14/15 dead names → `unresolvable_no_price_history`** (Yahoo carries no history at all for
  them: FRC, SIVB, ATVI, TWTR, SGEN, SPLK, VMW, MON, TIF, ETFC, WORK, XLNX, MXIM, ALXN).
* **1/15 → `resolved_then_buried`** (JUNO: r_1w +11.91% and three more horizons genuinely
  measured, r_12m buried as `no_price_history`) — exactly Decision 4's partially-measured case.
* **0 fabricated tails.** No dead name reached `resolved_fully`, and none carried five horizons.
* Controls AAPL/MSFT → `resolved_fully` (5 horizons each); filler 25/25 `resolved_fully`. The
  probe therefore fails in both directions, not just one.

`mask_stale_tail=True` does what the Task-5 review claimed it does. Resolution `--apply` was
released on this evidence.

### P0 — the resolver cannot measure a 20-year universe (blocks the study, not the ingestion)

`run_history_resolve` groups the open queue into alphabetical chunks of 50 tickers and skips a
whole chunk when more than `MAX_MISSING_SHARE = 0.30` of its tickers come back without a price
column, on the reasoning that "mass failure smells like throttling, not like 20 simultaneous
delistings" (`run_history_resolve.py:167`). That reasoning holds for the live lanes. It does not
hold for a 2006→ universe, where **32%–94% of the tickers in a given alphabetical range really
are delisted**. Measured over the two passes:

| | Pass 1 (50,945 open) | Pass 2 (49,870 open) |
|---|---|---|
| chunks measured | 4 / 180 | **0 / 177** |
| chunks skipped, `>30% ohne Spalte` | 111 (31,583 events) | 129 |
| chunks skipped, `Benchmark SPY fehlt` | 65 (18,084 events) | 47 |
| newly resolved | 991 | **0** |

The second pass resolved nothing and the structural guard fired on *more* chunks than the first
(129 vs 111), because every live name that resolves leaves the queue and raises the dead share of
what remains. **The loop diverges: re-running makes coverage worse, never better.** The
`Benchmark SPY fehlt` chunks are genuine transient Yahoo throttling and would self-heal; the
`>30%` chunks never will.

Consequence for the numbers below: the measured slice is not a random sample of the corpus. It is
precisely those alphabetical ticker ranges that happened to contain the *fewest* delistings — a
survivorship bias on top of the one the report's disclaimer already states. Treat the effect sizes
as an upper bound of an upper bound.

Not fixed here on purpose: `MAX_MISSING_SHARE` is Task 5's constant, reviewed and ratified, and
Task 7's scope is the runner plus the first run. Needs Nico / the controller. The plausible fix is
an additive resolver parameter (default = live behaviour unchanged) that raises or disables the
share guard for the history job, keeping the per-ticker re-check as the burial gate — the re-check
is what actually distinguishes a throttle from a delisting, and the probe shows it works.

### Coverage / survivorship (from `docs/research/history-study-report.json`)

Columns are disjoint and sum to the event count (a partially-measured row counts as measured,
not as untouched — it is also still `open`, which is why the report's `offen` is larger).

| Class | Events | r_1w measured | all 5 measured | unresolvable | never evaluated |
|---|---|---|---|---|---|
| congress & executive | 23,274 | 1,027 (4.4%) | 448 (1.9%) | 35 (`no_price_history` 33, `benchmark_self` 2) | 22,212 (95.4%) |
| insider clusters | 27,681 | 454 (1.6%) | 439 (1.6%) | 163 (`no_price_history` 100, `panel_gap` 63) | 27,064 (97.8%) |
| statements | 0 | — | — | — | measured negative result, not a gap |
| **total** | **50,955** | **1,481 (2.9%)** | **887 (1.7%)** | **198 (0.4%)** | **49,276 (96.7%)** |

The `unresolvable` column — the survivorship bucket this study exists to count honestly — is
**0.4%**, which is far too small to be believable for a 2006→ universe and is itself an artefact
of the P0: the delisted names are sitting in the never-evaluated column instead of being counted.
The probe proves they *would* be counted correctly if the chunks were ever measured.

### First base-rate table (relative to SPY, entry = close of first panel date ≥ t0)

> **Caveat, carried inline per the Task-6 review:** "N cells with direction agreement" is **not**
> a P2 go/no-go input — the gate is a sign comparison, not a significance test. The report emits
> 54 gated cell-horizons, 38 direction-agreeing, ~27 expected from pure noise. The decision-grade
> outputs are the coverage block above and the effect sizes against their stderr below. On 1.7%
> coverage from a non-random slice, neither supports a lane decision yet.

| Class | Horizon | n | hit rate (fit / validate) | Ø rel. return ± stderr |
|---|---|---|---|---|
| congress | r_1w | 1,027 | 58.3% (49.4 / 62.5) | **+0.74% ± 0.12pp** |
| congress | r_1m | 1,005 | 46.1% (45.1 / 46.5) | +0.42% ± 0.30pp |
| congress | r_3m | 535 | 42.4% (42.6 / 42.1) | **−1.68% ± 0.61pp** |
| congress | r_6m | 495 | 40.6% (39.0 / 43.8) | **−2.44% ± 0.90pp** |
| congress | r_12m | 448 | 41.3% (42.3 / 38.5) | **−3.52% ± 1.50pp** |
| insider clusters | r_1w | 454 | 52.2% (55.4 / 44.9) | +1.29% ± 0.59pp |
| insider clusters | r_1m | 454 | 51.8% (53.8 / 47.1) | +0.81% ± 0.85pp (directions disagree) |
| insider clusters | r_3m | 451 | 50.1% (50.6 / 48.9) | +6.25% ± 3.16pp |
| insider clusters | r_6m | 448 | 48.7% (52.2 / 40.2) | +12.70% ± 6.60pp |
| insider clusters | r_12m | 439 | 43.3% (50.0 / 26.0) | +11.45% ± 6.86pp (directions disagree) |

Read with the caveat above, the only effects clearing ~2 stderr are congress's **negative** medium-
horizon means (r_3m −2.8σ, r_6m −2.7σ, r_12m −2.3σ) alongside a small positive r_1w (+6σ, but on a
0.74% mean — plausibly the filing-day drift, not a tradable edge after costs). Congress purchases
under-performing SPY over 3–12 months would kill that lane cheaply, which the plan explicitly
names as a valid result — but not on 1.9% coverage of a slice selected for survivorship. The
insider r_6m/r_12m means are large and entirely inside their own stderr, and their fit/validate
hit rates diverge hard (52.2 → 40.2, 50.0 → 26.0), i.e. no stable direction.

### Verdict (superseded — see the post-fix rerun below)

Ingestion and enforcement are done and correct. The study is **not** ready to inform P2: it needs
the P0 resolved and a re-run, after which the coverage block is the first thing to re-read. No
lane should be designed or killed on this table.

*(Done: a52be5b runner + 26 tests, gate 1718 green; report JSON + this Outcome in the follow-up
commit. Live runs 2026-08-07: congress 23,274, form4 82/82 quarters → 27,681, statements 0/10
buried, probe PASSED, resolve 1,481 measured of 50,955.)*

### Post-fix rerun — 2026-08-07 19:36–20:26 CEST (final)

After `e65cf4e` (history-mode guard overrides) the driver (`scripts/drive_history_resolve.sh`,
`--max-missing-share 1.0 --max-rechecks 50`) converged in **two passes** (~50 min): pass 1
resolved 33,167 events (28,583 fully, 4,542 partially, 42 partially+delisted) and buried 16,050
(13,710 `no_price_history` — the survivorship bucket the old guard hid in "never evaluated" —
2,286 `panel_gap`, 54 `benchmark_self`); pass 2 moved nothing → converged. 5,237 stay open
legitimately (young events / capped rechecks, drain on future runs).

**Coverage per class:** congress & executive filers 23,274 events, 2,411 unresolvable, 4,505 open,
~16–21k measured per horizon; insider clusters 27,681 events, 13,837 unresolvable (insider
mortality is real: half the 2006→ cluster names are gone), 732 open, ~13–14k measured per horizon.
Multiplicity header: **162 cell-horizons gated, 92 direction-agreeing, ~81 expected from noise.**

| Class | Horizon | n | hit (fit / val) | Ø rel. return ± stderr |
|---|---|---|---|---|
| congress | r_1w | 20,792 | 50.5 (49.5 / 51.5) | +0.15% ± 0.03pp (directions disagree) |
| congress | r_1m | 20,114 | 47.7 (48.0 / 47.3) | +0.06% ± 0.07pp |
| congress | r_3m | 19,218 | 46.4 (47.8 / 44.7) | −0.22% ± 0.13pp |
| congress | r_6m | 18,544 | 45.0 (46.4 / 43.1) | −0.63% ± 0.19pp |
| congress | r_12m | 16,358 | 43.7 (45.9 / 39.7) | −0.39% ± 0.33pp (directions disagree) |
| insider clusters | r_1w | 13,856 | 51.6 (51.7 / 51.0) | **+2.08% ± 0.97pp** |
| insider clusters | r_1m | 13,856 | 48.4 (49.0 / 46.4) | +10.49% ± 8.15pp (outlier-driven stderr) |
| insider clusters | r_3m | 13,694 | 47.0 (48.3 / 42.9) | **+2.55% ± 0.67pp** |
| insider clusters | r_6m | 13,492 | 44.7 (46.3 / 39.6) | +4.12% ± 1.15pp (directions disagree) |
| insider clusters | r_12m | 13,112 | 43.3 (46.2 / 32.9) | +7.91% ± 1.64pp |

**Reading (with the standing caveats — direction agreement is a sign test, not significance; 162
gated cells expect ~81 spurious agreements):** full coverage substantially revises the biased
1.9% slice above — congress's "strong negative" medium horizons shrink to −0.2…−0.6% (tiny, and
r_12m directions disagree); the congress lane shows **no economically meaningful edge in either
direction** on 16–21k measurements per horizon. Insider clusters keep positive means clearing
2–3 stderr on r_1w/r_3m/r_12m, but validate hit rates decay hard with horizon (51.0 → 32.9),
and the means sit far above the hit rates — outlier-carried, not broad-based. **Decision-grade
inputs for P2 are this coverage block and the effect sizes vs stderr — Nico's call, not the
loop's.** Statement class: measured dead (0/10 genuine), published as an explicit negative.

*(Rerun commits: e65cf4e resolver overrides, 3724227 runner hardening; report JSON refreshed by
the driver and committed with this Outcome. Full form4 walk was ~7 min, not multi-hour as planned
— the SEC ZIPs are small; the resolve pass dominated at ~48 min.)*
