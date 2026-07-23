# Spec: Vision v13 — "Trust & Honest Fills" (2026-07-23)

**Nico directive (2026-07-23):** "Ich will damit später reich werden — alles dranlegen, dass der
Autotrader krass wird. Review, alles, richtig voranbringen." Autonomous session, subagent-driven,
token-frugal. Hard constraints unchanged: paper-only, local & free, honest framing, no order routing.

## Grounding (three-track discovery, 2026-07-23)

**Adversarial core review** (verified by reproduction against `advance_autotrader`):
- **P0-A: Arena fund-share P&L is silently lost forever.** `nightly_train.sh` runs `autotrader`
  BEFORE the lanes; `_asset_return`'s on-or-before fallback resolves both window ends to the same
  stale price → 0% return; the next run re-anchors at that same price, so the real move is never
  booked. Once a lane is promoted, its entire P&L would vanish from the depot.
- **P0-B: `combined_panel` docstring lies.** It claims "no common-range trim" but calls
  `clean_panel`, which trims to the LATEST first-valid date across all tickers — one young
  watchlist ticker (e.g. a fresh IPO) silently truncates every other stock's history.
- P1: `proof.cost_share_of_pnl` uses `abs(net)+costs` as denominator — understates cost burden
  exactly for loss-making books (net=−100, costs=80 → 44% instead of 400%).
- P1: `_asset_return`'s silent 0.0 fallback freezes any position without a current price forever
  (no exit possible; delistings/feed gaps).
- P1: promotion gate reads lane trades with `limit=5000` while claiming all-time metrics.
- P2: `run_swing` computes free slots before the day's exits.

**Backlog triage:**
- Form-4 XML bug already fixed (commit `e31436f`) — PLAN.md checkbox stale.
- entry_tb blocker root cause is NOT `--start` (already 2007): `clean_panel` trims to the latest
  first-valid date; SNDK (Feb-2025 IPO) drags the whole panel start to 2025-02 → only 4 monthly
  as_of splits vs 28 required. Fix = minimum-history pre-filter before panel build.
- Ledger has no `dsr_hurdle` column (positional inserts, 4519 rows) — blocks auditability and the
  future strategy-parameter search.
- voices: single-token company names (SHEL.L "Shell", TGT "Target", NXT.L "Next") bypass the
  `_GENERIC_FIRST_WORDS` gate (only applied in the multi-word branch); the frozenset is a manual
  snapshot with no drift check.
- Kelly sizing: NOT actionable (3 rebalance days, no realized-trade concept in depot schema).
  Shorts-with-borrow and strategy-parameter search deferred (L each).

**SOTA self-challenge (standing mandate, sourced):**
- Next-open fills close a documented look-ahead caveat (signal and fill on the same close).
- Corwin-Schultz high-low spread estimator upgrades the flat-10bps cost assumption to a
  liquidity-aware floor — needs OHLC, which the panels don't carry yet (close-only).
- Walk-forward efficiency (WFE = OOS/IS) as a cheap third overfitting signal next to DSR/PBO.
- Rejected as academic decoration: online-learning meta-allocation, SPA test. Deferred pending
  offline evidence: continuous regime multiplier, HRP-over-sleeves comparison.

## Scope decision

v13 = **make the numbers trustworthy, unblock the core ML model, make execution honest.**

1. **Wave R — hardening:** fix both P0s + the three P1s + the P2 (chain order, valuation marks,
   gap-tolerant panel, stale-position handling, cost-share formula, unlimited promotion trades,
   swing slot order).
2. **Wave Q — unblock & quality:** entry-panel minimum-history pre-filter (unblocks walk-forward),
   ledger `dsr_hurdle` column, WFE metric (logged, soft), voices single-token gate + drift scan,
   FetchStats visibility + stale PLAN.md cleanup.
3. **Wave O — honest execution (depot only):** OHLC panel loader, next-open fills for the
   Auto-Depot via persisted pending orders (sleeves stay close-fill as signal layer — documented),
   Corwin-Schultz spread cost floor `max(10 bps, half CS spread)` labelled as a lower bound.

**Out of scope (backlog, with reasons):** strategy-parameter search (L, needs Q-ledger first),
bearish-call signed ledger resolution (M, long-only system → not trust-critical), Kelly sizing
(insufficient data + missing realized-trade concept), shorts borrow realism (L), continuous
regime multiplier / HRP (need offline comparison evidence first, else churn).

## Non-negotiables for every task

Gate `uv run pytest -q` + `uv run ruff check .` green before commit (FE tasks additionally
typecheck+build — v13 has no FE tasks). Paper-only, free data, deterministic tests (fakes, no
network). Honest labels on every new metric (lower-bound costs, soft WFE). Branch `autopilot/work`.
