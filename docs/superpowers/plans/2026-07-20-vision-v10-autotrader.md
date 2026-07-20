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

- [ ] **B1 runner** — `scripts/run_autotrader.py`: combined panel (ETF snapshot ⋈ ML-bots snapshot
  ⋈ SPY, column-wise), sleeves = default_strategies() minus Ensemble + ready ML bots, monthly
  weight recompute via `state_storage` KV (`autotrader_weights_month`), protections chain, advance,
  persist, EUR spot into valuation, stdout summary. `--dry-run` prints without persisting. Test:
  end-to-end on synthetic panel with FakeProvider-style stubs (no network).
- [ ] **B2 cron step** — `daily_copilot.sh`: step `autotrader` after `lanes`, before `digest`
  (degrade-independently). Doc line in script header. Test: n/a (shell), verify via live smoke D2.

## Wave C — surfaces

- [ ] **C1 digest section** — `digest.py::build_digest` new optional param `autodepot` (dict) →
  "🤖 Auto-Depot" block (equity €/$, day/total vs SPY, exposure, trades capped 5, risk events,
  weight mode); collector in `run_digest.py` reads autotrader DB. Tests: section renders, absent
  when no account, HTML + plain variants.
- [ ] **C2 API** — `api.py`: `/api/autodepot` (account, valuations, trades ≤ 50, sleeve weights,
  risk events ≤ 20), shape follows `/api/forward`. Tests: endpoint with seeded tmp DB, empty-state.
- [ ] **C3 frontend** — `DepotsView.tsx`: 5th tab "Auto-Depot"; new `AutoDepotPanel.tsx` (equity
  curve vs benchmark, sleeve-weight list with mode badge, trades table, risk-event list, EUR line
  with translation P&L separated); `api.ts` `fetchAutodepot` + types. German UI copy + DISCLAIMER.
  Gate: typecheck + build.

## Wave D — closure

- [ ] **D1 docs** — README section "Auto-Depot" (honest framing, params, caveats: anchor phase,
  close-fill convention, no-Kelly-yet, next-open-fill backlog); broker-seam facts paragraph
  (Alpaca/T212/IBKR, "requires Nico + LOOP.md constraint change"); PLAN.md phase entry.
- [ ] **D2 live smoke + outcome** — run `scripts/run_autotrader.py` for real (network ok, local),
  verify valuation/trades/digest section render, then fill outcome section below. Full gate green.

## Outcome

_(filled after D2)_
