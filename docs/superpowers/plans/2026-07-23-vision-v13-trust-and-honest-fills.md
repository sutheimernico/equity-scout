# Plan: Vision v13 — "Trust & Honest Fills" (hardening · ML unblock · honest execution)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (or
> executing-plans). One task per dispatch, checkbox (`- [ ]`) tracking. Gate per task:
> `uv run pytest -q` + `uv run ruff check .`. Conventional Commits, English, imperative.
> Branch `autopilot/work`. Paper-only, local & free, deterministic tests (fakes, no network).

**Spec:** `docs/superpowers/specs/2026-07-23-vision-v13-trust-and-honest-fills.md`

**Goal:** Fix the two verified P0s (arena fund-share P&L silently lost; young ticker truncates
the shared panel) plus the P1/P2 review findings, unblock entry_tb walk-forward training via a
minimum-history pre-filter, and make Auto-Depot execution honest (next-open fills + liquidity-aware
Corwin-Schultz cost floor on a new OHLC panel world).

**Architecture notes:**
- Valuation correctness moves from "resolve both window ends on-or-before" to **persisted
  per-position marks**: the depot remembers the last price it actually used per ticker and books
  the full move once a fresh price appears. No P&L can be lost to chain-timing anymore.
- The OHLC world is **additive**: a new loader/module; existing close-only consumers untouched.
  Only the Auto-Depot switches to next-open fills (pending orders persisted in the account blob);
  forward-paper sleeves deliberately stay close-fill as the signal layer — documented.

---

## Wave R — hardening (R1 first; R2 before R4)

- [x] **R1 (P0) nightly chain order: lanes before depot** — `scripts/nightly_train.sh`: move the
  `st_swing` (and any other lane steps living in this chain, incl. the overnight session sweep)
  BEFORE the `autotrader` step, so the depot values today's lane equity, not yesterday's. Keep
  heartbeat/flock semantics untouched. Update the inline comment explaining WHY the order is
  load-bearing (depot reads lane equity series). Test: `tests/test_nightly_chain_order.py` —
  parse the script text and assert the lane step lines appear before the autotrader line (simple,
  honest guard against regression; pattern exists in other wrapper tests).
- [x] **R2 (P0) per-position valuation marks in the depot** — `src/equity_scout/forward_paper.py`
  `_asset_return` (~107–116): return `None` when the ticker column is missing OR no price row
  strictly newer than `start` exists (distinguish "no fresh price" from "0% return"); keep the
  existing behavior available to callers that treat `None` as carry.
  `src/equity_scout/autotrader_engine.py` (~160–169): add persisted marks `last_marks:
  dict[ticker, price]` to the depot account blob (`autotrader_storage` round-trip; older blobs
  without the key migrate to `{}` and initialize marks from the first resolved prices with a
  logged one-off "mark init" note). Position return = resolved_price / last_mark − 1, computed
  ONLY when a price strictly newer than the mark's date exists; otherwise carry the position
  unchanged and KEEP the old mark so the full move books on the next run. Update marks after each
  valuation. Tests (`tests/test_autotrader_engine.py`): reviewer repro — lane equity series gets
  its fresh row only AFTER the depot run → that advance carries (0 booked), the NEXT advance books
  the full move (no loss); fresh-price path unchanged; blob without `last_marks` loads cleanly.
- [x] **R3 (P0) gap-tolerant combined panel** — `scripts/run_autotrader.py:98–112`
  `combined_panel`: load the stock subpanel via the gap-tolerant path
  (`load_price_history`/`clean_columns`, as used elsewhere in the repo) instead of
  `load_etf_panel`/`clean_panel`, so one young ticker cannot truncate the others; docstring then
  matches reality. Tests (`tests/test_run_autotrader.py`): synthetic panel where one ticker starts
  10 days ago and another has 2 years → the old ticker's history stays full length; NaN gap
  handling still tolerated by consumers (existing behavior asserted).
- [x] **R4 (P1) stale positions in forward paper must not freeze silently** —
  `src/equity_scout/forward_paper.py` (~169, consumer of `_asset_return`): a held position whose
  return resolves to `None` is carried unchanged BUT counted per-position as
  `stale_days += 1` (persisted in the account state); once `stale_days > 5` trading steps, close
  the position at its last known price with `exit_reason="stale_no_price"` and log loudly.
  Fresh price resets the counter. Tests (`tests/test_forward_paper.py`): ticker column disappears
  → position carried, counter rises, force-closed on step 6 with the stale reason; price returns
  on step 3 → counter reset, normal valuation.
- [x] **R5 (P1) honest cost share** — `src/equity_scout/proof.py:78–81`:
  `gross = abs(sum(realized_pnls) + costs_paid)` (pre-fee P&L magnitude) instead of
  `abs(sum(...)) + costs_paid`. Tests (`tests/test_proof.py`): net=−100, costs=80 → cost_share
  4.0 (costs turned a profitable book negative); profitable book value unchanged sanity case;
  zero-gross guard stays None/0 as currently designed.
- [ ] **R6 (P1) promotion gate reads ALL lane trades** — `scripts/run_autotrader.py:153`:
  drop `limit=5000` for the promotion-gate path (or pass `limit=None` end-to-end through
  `load_lane_trades`) so all-time net_pnl/profit_factor are truly all-time. Tests
  (`tests/test_shortterm_storage.py` or promotion tests): >limit rows in a tmp DB → gate sees all.
- [ ] **R7 (P2) swing frees slots before entering** — `scripts/run_shortterm.py` (~70/86): run
  `check_exits` BEFORE `pick_entries` (or recompute free slots after exits) so capital freed today
  is investable today. Tests (`tests/test_run_shortterm.py`): book at max positions with one exit
  due today + one fresh signal → exit books first, entry fills the freed slot.

## Wave Q — ML unblock & quality

- [ ] **Q1 (high) entry-panel minimum-history pre-filter** — `scripts/run_train_entry.py`
  (`_resolve_tickers`/`_load_panel`): before panel build, drop tickers whose first valid price is
  later than a threshold (e.g. panel would lose >30% of its span; make the rule explicit and
  logged: "excluded SNDK: history starts 2025-02-13, panel starts 2007-01-03"). `clean_panel` then
  trims to the SURVIVORS' latest first-valid date. Also correct the stale PLAN.md backlog wording
  (the `--start` diagnosis was wrong — root cause is the trim in `data/etf_panel.py::clean_panel`).
  Tests (`tests/test_run_train_entry.py` or `test_etf_panel.py`): synthetic set with one young
  ticker → panel keeps the long span, young ticker excluded and logged; all-young edge case →
  loud error, no silent empty panel.
- [ ] **Q2 (high) ledger records the DSR hurdle per trial** — `src/equity_scout/ml/ledger.py`:
  idempotent migration `ALTER TABLE trials ADD COLUMN dsr_hurdle REAL` (guarded by PRAGMA
  table_info check, existing 4519 rows keep NULL), `record_trial(...)` gains the parameter, all
  call sites (`research_loop.py`, `ml/search.py`) pass the hurdle valid at trial time. Tests
  (`tests/test_ledger.py`): fresh DB round-trips the value; pre-migration DB file opens and
  migrates; old rows read as None.
- [ ] **Q3 (soft) walk-forward efficiency metric** — where walk-forward results are aggregated
  (`ml/` training/report path used by `run_train_entry.py`): compute
  `wfe = oos_metric / is_metric` (guard is_metric ≤ 0 → None) per candidate, persist it alongside
  existing champion/report fields (`champion_history` or the training report — follow the existing
  storage pattern), and show it in the trainer log line. SOFT signal only in v13 — no gate change;
  label "WFE <0.5 = likely overfit (heuristic)". Tests: known IS/OOS pair → expected ratio;
  is_metric=0 → None, no crash.
- [ ] **Q4 (quick win) voices single-token gate + drift scan** — `src/equity_scout/evidence/
  voices.py::resolve_ticker`: apply the `_GENERIC_FIRST_WORDS` gate in the single-token branch
  (`elif norm_name:`) too, so "Shell"/"Target"/"Next" headlines no longer resolve to
  SHEL.L/TGT/NXT.L; prefer multi-word matches over single-token when both hit. New
  `scripts/scan_generic_words.py`: compare universe first-words against the snapshot frozenset,
  print additions/removals (exit 0 always — informational). Tests (`tests/test_voices.py`):
  the three concrete false-positive headlines stop resolving; genuine multi-word names still
  resolve; scanner flags a synthetic new generic word.
- [ ] **Q5 (XS) FetchStats visibility + stale plan cleanup** — `scripts/run_scout.py`: log one
  FetchStats summary line at end of run (fetched/cache-hits/errors/rate-limited + duration) from
  the existing data-quality report objects. Tick the stale Form-4 checkbox in PLAN.md (fixed by
  `e31436f`, verified in triage 2026-07-23) and fix the Q1-related backlog wording. Test: summary
  line renders from a fake FetchStats (pure function).

## Wave O — honest execution (depot only; O1 → O2 → O3)

- [ ] **O1 OHLC panel loader** — new `src/equity_scout/data/ohlc_panel.py`:
  `load_ohlc_panel(tickers, start, ...) -> dict[str, DataFrame]` (or MultiIndex frame — pick the
  simplest shape consumers need: per-ticker OHLC columns), same provider/cache seams and
  conventions as the existing close panel (read-through cache, no live calls in tests), young/gappy
  tickers tolerated per ticker. Close-only consumers stay untouched. Tests
  (`tests/test_ohlc_panel.py`): fake provider round-trip, cache hit path, missing ticker → absent
  key not crash.
- [ ] **O2 next-open fills for the Auto-Depot** — `src/equity_scout/autotrader_engine.py` +
  `autotrader_storage.py` + `scripts/run_autotrader.py`: an advance no longer fills its own
  rebalance trades at today's close; instead it persists `pending_orders` (ticker, target delta,
  decided_as_of) in the account blob, and the NEXT advance fills them first at that day's OPEN
  from the OHLC panel (fallback when open missing: that day's close + loud log, honest label in
  the trade row `fill="open"|"close_fallback"`), then computes new targets. Costs at fill time.
  Valuation marks (R2) unaffected — marks track valuation, fills track execution. Older blobs
  without `pending_orders` migrate to `[]`. Digest/`/api/autodepot` surfaces state the convention
  ("Fills: next-open since v13"). Tests (`tests/test_autotrader_engine.py`): trades decided on
  day t fill at open(t+1) with costs; missing open → close fallback labelled; idempotent re-run
  same day does not double-fill; legacy blob migrates.
- [ ] **O3 Corwin-Schultz cost floor** — new `src/equity_scout/costs.py`:
  `cs_spread(high, low) -> float` per Corwin-Schultz (2012) two-day estimator, rolling 21-day
  median per ticker, clip negatives to 0; depot cost per fill =
  `max(10 bps, cs_spread/2) * notional`, labelled everywhere as a LOWER BOUND (underestimates
  thin names). Wire into O2's fill path via the OHLC panel; sleeves keep flat 10 bps (signal
  layer, documented). README cost-model paragraph + proof view label updated. Tests
  (`tests/test_costs.py`): hand-computed synthetic H/L series matches expected CS value;
  negative-spread days clipped; missing OHLC → falls back to flat 10 bps with log.

## Closure

- [ ] **D1 docs & plan closure** — README: fixed P0s (one honest paragraph in the proof/caveats
  section), fill+cost convention change with date; PLAN.md: v13 phase section with outcome notes;
  AUTOPILOT_LOG one-liner. Update `docs/superpowers/plans/2026-07-23-vision-v13-trust-and-honest-fills.md`
  outcome section (deviations, open ends).

## Backlog seeded by v13 (not tasks — reasons in spec)

- Strategy-parameter search with own ledger+DSR hurdle (after Q2; v14 candidate, L).
- Signed ledger resolution for bearish voice calls (M).
- Kelly sizing: still blocked (needs realized-trade concept + ~50 trades of history).
- Shorts in lanes with borrow/margin realism (L).
- Continuous regime multiplier & HRP-over-sleeves: only after an offline comparison study proves
  a benefit vs. the current step function / Sharpe-softmax.
