# Plan: Vision v10 — Autotrader ("Auto-Depot")

**Spec:** `docs/superpowers/specs/2026-07-20-vision-v10-autotrader.md` · **Branch:** `autopilot/work`
**Gate per task:** `uv run pytest -q` + `uv run ruff check .` (FE tasks also `npm run typecheck` + `npm run build`) · Conventional Commits.

Research grounding (2026-07-20 session): 1/N-anchor blending (DeMiguel et al. 2009,
arxiv 2504.02841), vol targeting (Moreira & Muir 2017, Bongaerts et al. 2020), stateful stackable
protections (freqtrade), allocation/risk as separate layers (QuantConnect LEAN), trades as
first-class rows for a broker seam (nautilus RiskEngine idea), broker facts (Alpaca/T212/IBKR docs).

## Wave A — pure core (each: module + tests, no I/O)

- [x] **A1 allocator** — `src/equity_scout/autotrader_allocator.py`: `sleeve_returns` (daily
  returns from forward_valuations equity series, per strategy), `blend_weights(returns, window=63,
  anchor=0.5, floor=0.05, cap=0.40)` → dict + mode ("anchor"|"tilt"); < 60 overlapping obs → pure
  EW with mode "anchor". Tests: EW fallback, softmax tilt ordering, floor/cap renorm, walk-forward
  (no future rows used).
- [x] **A2 protections** — `src/equity_scout/autotrader_protections.py`: `ConcentrationCap(0.10)`,
  `RegimeGate(red→0.5)`, `VolTarget(0.12, window=20)`, `DrawdownBreaker(soft=0.10, hard=0.20,
  cooldown_days=10, recover=(0.08, 0.15))` — each `apply(weights, ctx) → (weights, event|None)`;
  breaker is stateful via ctx (stage, triggered_at). Tests per protection incl. hysteresis path
  up/down, unknown-regime no-op, vol-target inactive < 21 points.
- [x] **A3 engine** — `src/equity_scout/autotrader_engine.py`: `aggregate_targets(sleeve_weights,
  sleeve_decisions)` (look-through, per-ticker netting), `advance(account, targets, panel, as_of)`
  — mark-to-market by weight drift, turnover costs 10 bps, borrow proxy on net short, margin
  floor, produces trade rows (delta_weight, notional, cost). Idempotent per date. Tests mirror
  `test_forward_paper.py` (idempotency, no-lookahead, netting long vs short, cost charge, trades).
- [x] **A4 storage** — `src/equity_scout/autotrader_storage.py`: tables per spec §5, own
  `init_autotrader_db`, save/load account round-trip, insert-or-ignore valuations/trades/events,
  sleeve-weights upsert per month. Tests: round-trips via tmp_path, idempotent double-insert.

## Wave B — pipeline

- [x] **B1 runner** — `scripts/run_autotrader.py`: combined panel (ETF snapshot ⋈ ML-bots snapshot
  ⋈ SPY, column-wise), sleeves = default_strategies() minus Ensemble + ready ML bots, monthly
  weight recompute, protections chain, advance, persist, EUR spot into valuation, stdout summary.
  `--dry-run` prints without persisting. Test: end-to-end on synthetic panel, no network.
  _Deviation:_ month gate reads `MAX(month)` from `autotrader_sleeve_weights` instead of a
  `state_storage` KV — one source of truth less to keep in sync.
- [x] **B2 cron step** — _Deviation (better slot):_ step `autotrader` appended to
  `nightly_train.sh` AFTER `forward_paper --refresh`, NOT into the 18:00 `daily_copilot.sh` —
  at 18:00 Berlin the US market is open, the depot would fill on an intraday stand; nightly it
  trades the real close right after the sleeves advanced. The daily digest only reads the DB.

## Wave C — surfaces

- [x] **C1 digest section** — `digest.py::build_digest` new optional param `autodepot` (dict) →
  "🤖 Auto-Depot" block (equity €/$, day/total vs SPY, exposure, trades capped 5, risk events,
  weight mode); collector in `run_digest.py` reads autotrader DB. Tests: section renders, absent
  when no account, HTML + plain variants.
- [x] **C2 API** — `api.py`: `/api/autodepot` (account, valuations, trades ≤ 50, sleeve weights,
  risk events ≤ 20), shape follows `/api/forward`. Tests: endpoint with seeded tmp DB, empty-state.
- [x] **C3 frontend** — `DepotsView.tsx`: 5th tab "Auto-Depot"; new `AutoDepotPanel.tsx` (equity
  curve vs benchmark, sleeve-weight list with mode badge, trades table, risk-event list, EUR line
  with translation P&L separated); `api.ts` `fetchAutodepot` + types. German UI copy + DISCLAIMER.
  Gate: typecheck + build.

## Wave D — closure

- [x] **D1 docs** — README section "Auto-Depot" (honest framing, params, caveats: anchor phase,
  close-fill convention, no-Kelly-yet, next-open-fill backlog); broker-seam facts paragraph
  (Alpaca/T212/IBKR, "requires Nico + LOOP.md constraint change"); PLAN.md phase entry.
- [x] **D2 live smoke + outcome** — run `scripts/run_autotrader.py` for real (network ok, local),
  verify valuation/trades/digest section render, then fill outcome section below. Full gate green.

## Outcome (2026-07-20)

**All 11 tasks DONE in one session** (waves A–D, single-threaded, gate green per commit).

**Live smoke (real run, panel to 2026-07-16):** first advance booked 14 trades building the
initial book at 75 % gross exposure across 8 sleeves (7 rule-based + ML Long Bot; short bot
honestly absent — no champion). Allocation correctly in **anchor mode** (equal weight — the
sleeves' forward histories are too short to tilt on). The **ConcentrationCap fired live**
(SPY and VEU clipped to 10 %, risk event persisted and rendered). EUR spot conversion live
(99,925 USD / 87,514 EUR). Second run on the same panel date: idempotent no-op, verified.
`/api/autodepot` served the real DB (curve 1 point, 14 trades, 8 sleeve rows, 1 risk event).
Digest block renders in plain + HTML with the depot's own as_of stamp. `autotrader.db` is
covered by the existing `*.db` gitignore rule.

**Gate:** 997 tests collected (941 → 997), full run green + ruff clean + FE typecheck/build
green. One full-suite run hit the KNOWN pre-existing flake
(`test_entry_model::test_calibrated_model_scores_through_the_calibrator`, unseeded numpy,
documented in PLAN "Needs Nico" since v9) — re-runs green 4/4, not v10-related.

**Deviations from plan** (both recorded inline at B1/B2): month gate via
`MAX(month)` in `autotrader_sleeve_weights` instead of a state KV; cron step in
`nightly_train.sh` after `forward_paper --refresh` instead of the 18:00 chain (real close
fills instead of an intraday stand). Also: `DrawdownBreaker.cooldown_days` counts CALENDAR
days (14 ≈ 10 trading days) — the protection context has no trading calendar, documented in
the docstring.

**Open (backlogged in PLAN.md):** next-open fills (needs an OHLC panel world), Kelly sizing
once ~50 realised trades exist. **Needs Nico:** nothing new beyond the standing items — the
nightly chain picks the depot up automatically; first tilt allocation ~3 months after the
sleeves accumulated 60 overlapping forward observations.

## v10.1 addendum — Always-on (same session, Nico: "passiv rund um die Uhr")

The v9 guaranteed-delivery architecture applied to the NIGHTLY chain, so the Auto-Depot's
track record accumulates without anyone thinking about it: `run_nightly_guarded.sh`
(flock + per-day marker; deliberately NO weekend skip — a Sunday catch-up of a missed
Saturday slot books Friday's close; the advance is idempotent so redundant runs are free),
persistent systemd user timer 02:35 Tue–Sat (INSTALLED + active, catch-up at WSL start),
crontab nightly line switched to the wrapper (installer executed under the project's
local-autonomy grant), Windows task XML `equity-scout-nightly` 02:40 staged
(registration = Needs Nico; it is the only layer that can wake the box). 3 wrapper tests
(subprocess seams: chain/state/log overrides). Gate green (1000 tests), tree clean.
