# Signal-Stack v5 — methodology hardening + insider evidence + model upgrade (2026-07-12)

**Trigger (Nico):** full concept review + "make it stronger" — use signals from people with good
track records, systematically try own parameters, train ML models that recognize entry
opportunities. Honest framing (no alpha promise) stays non-negotiable.

**Review basis:** three parallel review passes (ML methodology, evidence layer, overall concept),
2026-07-12. Key findings drive the packages below.

## Review findings (condensed)

**Critical / must fix before any expansion:**
- F1 `ml/meta_model.py:112` — purge/embargo arithmetic treats trading days as calendar days.
  At `horizon_days=42` (in the live search space) the real buffer shrinks to ~3 calendar days;
  one market holiday causes genuine train/test overlap → look-ahead in exactly the configs the
  DSR hurdle may crown as champion. Same helper reused by the entry model.
- F2 `ml/model_registry.py:112` — `promote_if_better` is a bare "strictly greater AUC" rule with
  no minimum delta, no minimum n_oos, and no multiple-testing protection. Nightly retrains are
  nightly trials; noise will eventually swap the champion. `_no_edge()` prints a warning but does
  not block promotion.
- F3 `ml/features.py:4` — docstring claims a one-day feature lag that does not exist in the code
  (the real lag lives in `_backtest_exposure`); misleading for future leakage audits.
- F4 `notify.py:129` — evidence-alert cooldown has no escalation: a 2-buyer alert suppresses a
  later 4-buyer cluster on the same ticker for 14 days.

**Biggest expansion levers (aligned with the vision):**
- L1 SEC Form 4 corporate-insider purchases as fourth evidence source (same httpx/EDGAR pattern
  as the 13F collector; feeds the existing ledger + person track records).
- L2 Entry-model upgrade: real OOS probability calibration, CatBoost preset, ensemble preset
  (deps already pinned). Registry gate from F2 keeps promotions honest.
- L3 Extend the auto-research loop to strategy parameters (vol-target/GEM/DAA knobs) with a
  SEPARATE trial ledger + DSR hurdle so two overfitting risks never share one accounting.
- L4 Visibility: evidence/person scores have zero dashboard surface; ML entry score is logged but
  never shown per ticker; no single per-ticker "signal stack" view across the five signal layers.

**Noted, deliberately not in scope now (backlog):**
- 13D/13G collector (fast >5% ownership signal, same submissions API as 13F).
- Cross-sectional ranking objective for the entry model (optimize Rank-IC directly).
- Rank-IC tracking for the screener funnel (ADR 0003 follow-up).
- kadoa congress mirror is a single point of failure feeding two pipelines (no free alternative
  identified; documented risk).
- PSR/DSR treats daily returns as i.i.d. while decisions are ~monthly — documented conservatism
  caveat, not a bug fix.

## Packages

1. **P1 methodology hardening** — fix F1 (trading→calendar day conversion + holiday buffer +
   regression test on a realistic calendar), F2 (promotion gate: min AUC delta, min n_oos, no
   promotion for no-edge models; first champion needs baseline quality), F3 (docstring).
2. **P2 Form 4 insider collector** — `evidence/form4.py` after the congress/edgar pattern
   (T0 = filing date, only transaction code P + acquired, PIT invariant, `unconfigured` without
   `EDGAR_USER_AGENT`); wiring into run_evidence/aggregate/alerts (`min_insiders` cluster
   threshold) + person track records; F4 escalation fix rides along (same files).
3. **P3 entry model v2** — OOS isotonic calibration, `catboost` + `ensemble` presets,
   `run_train_entry` trains all presets and lets the (now hardened) gate decide.
4. **P4 strategy-parameter search** — second search dimension in the research loop over strategy
   hyperparameters, own ledger table + own DSR trial counter, surfaced in `/api/research`.
5. **P5 signal stack + visibility** — ML score joined into `/api/radar` and shown in the radar,
   evidence panel (events/alerts/hit rates/person ranking), per-ticker signal-stack endpoint
   (`/api/stack/{ticker}`) bundling factor score, entry composite, ML score, evidence, person
   records in one view.

Order: P1+P2 parallel (disjoint files), then P3+P5 parallel, then P4. Gate per package:
`uv run pytest -q` green + `uv run ruff check .` clean (+ frontend typecheck/build for P5).
Commits by the orchestrator, one per package, Conventional Commits.

## Outcome

**2026-07-13:** P1 (methodology hardening, commit 36a0af6) and P2 (Form 4 insider collector,
commit 3b780b9) shipped with green gates. P3–P5 are superseded by — and folded into — the v6 plan
(`2026-07-13-always-on-copilot-v6.md`: P3→v6-P2, P4→v6-P7 backlog, P5→v6-P6), which extends the
scope per Nico's 2026-07-13 direction (voices evidence, ML bot family long/short, always-on
operation, IA overhaul).
