# equity-scout — LOOP (per-iteration prompt for the autonomous build agent)

You are a fresh headless agent. You do ONE high-value thing, verify it, commit it, and exit.
Progress lives on disk (this file, `PLAN.md`, git history, `AUTOPILOT_LOG.md`) — never in context.

## Per-iteration protocol
1. Read `~/private/AUTOPILOT.md` (global rules), then this `LOOP.md`, then `PLAN.md`.
2. Confirm you are on branch `autopilot/work` (the runner guarantees this; if not, stop).
3. Pick the SINGLE highest-value open `- [ ]` task in `PLAN.md` (top-to-bottom, earlier phases first).
   If a phase boundary is reached, run the once-per-phase self-challenge/SOTA step before proceeding.
4. Do that one task. Small, reviewable diff. Match existing repo conventions (read before writing).
   New logic ships with a test. Network/LLM access stays behind the existing seams and is faked in tests.
5. Run the gate: `uv run pytest -q` (green) AND `uv run ruff check .` (clean). If red, fix or revert.
6. On green: commit (Conventional Commits, English, imperative), check off the task in `PLAN.md`,
   append a one-line note to `AUTOPILOT_LOG.md`. Then exit.
7. If a task needs a paid resource or a Nico-only input: move it to "Needs Nico" in `PLAN.md`, pick
   another task, or exit. Never sign up for anything paid. Never fake data or metrics.

## Project-specific hard constraints (never override)
- **Local & free.** Data only from yfinance / SEC EDGAR (UA header) / public constituent lists.
  No paid feeds. **No real-money trading — ever.** Order routing to a PAPER broker account is
  allowed since 2026-08-04 (Nico's explicit decision, for the session lane on Alpaca Paper);
  a live/funded endpoint or live API key is never used. The loop never widens this line itself.
- **Honesty guardrails.** Every output surface carries the `DISCLAIMER`. The data-completeness gate
  stays mandatory. LLM theses are context-bounded interpretation, NEVER price forecasts — do not
  let the LLM "predict" or rank.
- **Determinism in tests.** No live network/LLM calls in tests; use `FakeProvider` / `FakeAnalysis`.
- **Pin new deps** with justification; prefer the simplest solution that meets the task.

## Measurement rules (learned 2026-08-11/12, the night the champion turned out to be an artifact)
Every one of these cost real time or real damage. They are cheap to follow and expensive to relearn.
- **Stamp the sample's IDENTITY, not just its size.** The live champion held its title for five
  weeks on an AUC measured over 220 rows while challengers were measured over 3 000+. The registry
  row recorded `n_train` but not WHICH universe — so two incomparable numbers looked comparable.
  Any metric that will later be compared must carry what it was measured on.
- **Never compare a stored metric against a fresh one.** Re-measure the incumbent on the
  challenger's own sample (`entry_model.evaluate_fitted_model`). Different samples, different
  numbers — the comparison is meaningless otherwise, however many decimals it has.
- **A gate that only checks on entry is half a gate.** The same bar that blocks a newcomer must be
  able to remove an incumbent (`model_registry.demote_if_no_edge`).
- **Overlapping windows are not independent observations.** A daily series of 20-day forwards
  shares 19 of 20 days; treating it as independent inflates every statistic by ~sqrt(h). Use
  `behaviour_study.independent_subsample`, and report the independent n.
- **For any estimator that SCALES something, judge ranking and calibration separately.** Raw VIX
  ranks forward volatility best and would still be wrong: it reads 36% high, and `VolTarget`
  divides by it. A perfect ranking with a wrong level is a permanent, invisible bias.
- **Measure one case before scaling to hundreds.** Checking a single EDGAR payload exposed two
  silent traps and one of my own errors; pulling 445 tickers first would have been slower AND
  quieter.
- **A change is not verified until its CONSUMER has run.** The demotion was "done" until an
  autotrader dry-run proved the depot survives a missing sleeve.
- **Rehearse destructive steps against a COPY of the DB, never production** — and when a repair
  script deletes, dry-run by default, `--apply` requires `--backup`.

## Gate (objective done-check)
`uv run pytest -q` green + `uv run ruff check .` clean. Commit only a green gate.

## Where things are
- Spec: `docs/superpowers/specs/2026-06-24-equity-scout-design.md`
- Code: `src/equity_scout/` (one responsibility per file) · Tests: `tests/` · CLIs: `scripts/`
- Run locally: `uv run python scripts/run_scout.py --provider yfinance` then `scripts/run_api.py`.
