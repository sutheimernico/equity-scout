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
- **Local & free.** Data only from yfinance / SEC EDGAR (UA header) / public constituent lists /
  Kraken public bars / Alpaca's free IEX data on the existing paper credentials (lane bars, and
  since 2026-08-17 the depot's read-only EOD price cross-check). No paid feeds, no new accounts.
  **No real-money trading — ever.** Order routing to a PAPER broker account is
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

## More measurement rules (learned 2026-08-23, the day a review caught four of my own numbers)
Same currency as the ones above: each cost real time or shipped a wrong claim.
- **A number you read off a picture is not a measurement.** Two tab-bar heights were quoted
  ~80 % too high because they were eyeballed from a Playwright screenshot taken at
  `deviceScaleFactor: 2` — image pixels, never halved. Measure the DOM
  (`getBoundingClientRect`, `scrollHeight`), or halve deliberately and say so.
- **A default in a counter invents data.** `details.get("kind", "context")` silently counted
  every source that has no `kind` field as a press mention and turned "205 of 262" into
  "475 of 589". When you aggregate, count the field's ABSENCE as its own bucket; a default
  is a fact you made up.
- **Constants shared with another system must be mirrored and tested, never retyped.**
  `people.ts` compared against `"13f"` while the backend emits `"thirteen_f"`
  (`SOURCE_13F`): three dead branches, 80 fund filings labelled "wird in der Presse
  erwähnt" in the view that asks who is BUYING. I then reproduced the bug in new code by
  copying the literal from the lines above it. Name the constant, mirror it from the
  source of truth, and assert the set against what the API really sends.
- **A test that only feeds the cases the code already handles proves nothing.** The label
  tests above passed for months without ever constructing a fund event. Feed the case you
  believe is handled — that is where the silence lives.
- **A binary rendering of a multi-valued field needs its invariant pinned by a test.**
  `verdictLine` renders "verdient Geld" vs "verliert Geld" and is only honest because
  `is_significant` implies a directional verdict. Nothing enforced that until it was
  written down as a test; an equivalence test added later would have made the cockpit
  claim a loss where the finding was "no effect".
- **Recommendations rot, and they rot silently.** "Run the machine 15:30–22:00 on trading
  days" was carried forward in every session doc after the SESSION lane was paused — while
  the gap-fade signal window is 15:00–15:28. Following it would have guaranteed the lane
  never places an order. Before repeating an instruction, check the thing it was about
  still exists. "(unverändert)" is a claim, not a disclaimer.
- **Check the weekday before diagnosing a dead chain.** Weekday-only crons are legitimately
  silent on a Sunday; that cost the first twenty minutes of 2026-08-23.

- **A function whose return value you discard is a function you did not call.** The ignition
  entry path called `settle_or_cancel(order)` — whose entire job is to produce the FINAL
  post-cancel fill state, and whose docstring describes the exact bug ("left four positions the
  book knew nothing about") — and then threw the answer away and `continue`d. MRVI was bought
  three times on 2026-08-19 (424 shares at the venue, 128 in the book) and nothing noticed for
  five days. When a helper exists because of a past incident, using it means using what it
  returns.
- **"Something filled" is not "filled".** The same path tested `if filled.filled_qty` for
  truthiness and booked a `partially_filled` order as complete: 128 of 141 shares. `await_fill`
  warns about this one line above the call site. A truthiness check on a quantity cannot tell
  partial from complete — compare against what was ordered, or use the settled state.
- **Nothing was comparing the book to the account.** Every chain was green, the watchdog said
  "alle Ketten am Leben", and the two ledgers had been 296 shares apart since the 19th. Heartbeat
  monitoring cannot see a state divergence; that needs its own check, and the check belongs where
  both numbers are already in hand.
- **A stale metric reads exactly like a current one.** The research ledger showed PBO 0.7714
  with no hint that it was computed on 2026-06-26 over 13 of what are now 4,600 trials, because
  `run_pbo.py` was never wired into a chain. A number that cannot refresh itself will be believed
  long after it stopped being true — schedule it or delete it.
- **Check which comparison the system actually makes before calling it broken.** I reported the
  DSR hurdle as "letting 98.6 % through" after comparing `sharpe_periodic > dsr_hurdle`. That is
  not a gate: the hurdle is the deflation benchmark passed INTO the PSR call (`ledger.py:144`).
  The real distribution (DSR median 0.946) shows a genuine problem for a different reason —
  4,600 correlated configs are not the independent trials the Gumbel term assumes. Reading the
  call site first would have cost a minute and saved a wrong recommendation.

## Gate (objective done-check)
`uv run pytest -q` green + `uv run ruff check .` clean. Commit only a green gate.

## Where things are
- Spec: `docs/superpowers/specs/2026-06-24-equity-scout-design.md`
- Code: `src/equity_scout/` (one responsibility per file) · Tests: `tests/` · CLIs: `scripts/`
- Run locally: `uv run python scripts/run_scout.py --provider yfinance` then `scripts/run_api.py`.
