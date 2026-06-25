# ADR 0002 — DSR and PBO as complementary, both-first-class overfitting guards

**Status:** Accepted (2026-06-26)

## Context

Phase-boundary self-challenge for the ML research loop (per AUTOPILOT's once-per-phase mandate).
The loop searches `MetaConfig` points (features × {elastic_net, random_forest, catboost} ×
lookback × horizon × triple-barrier), evaluates each out-of-sample via purged + embargoed
walk-forward, and stores compact per-trial stats (periodic Sharpe, n_obs, skew, kurtosis). It picks
the champion as the trial with the highest **Deflated Sharpe Ratio (DSR)**, where the deflation
hurdle (`expected_max_sharpe`) rises with the trial count — the built-in overfitting budget. A
separate CSCV-**PBO** (Probability of Backtest Overfitting) was computed occasionally via
`scripts/run_pbo.py`.

A sourced methodological review (López de Prado / Bailey et al.) surfaced two findings:

1. **DSR and PBO are not redundant — they answer different questions.** The DSR judges whether a
   *single* strategy is significant after correcting for the number of trials. PBO judges whether
   the *selection process itself* — taking the argmax over thousands of trials — is reliable.
   Selecting the max-DSR trial across ~4100 trials is a winner's-curse / max-of-noisy-estimators
   problem that the DSR alone does **not** fully correct; PBO is exactly the diagnostic for it
   ([Bailey & López de Prado 2014, *The Deflated Sharpe Ratio*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551);
   [Bailey, Borwein, López de Prado, Zhu 2017, *The Probability of Backtest Overfitting*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)).

2. **The hurdle assumes independent trials.** `expected_max_sharpe` uses N = nominal trial count and
   the empirical cross-trial Sharpe variance. With ~4100 highly correlated trials (reused features,
   adjacent lookbacks), the *effective* number of independent trials is far smaller, and a
   correctly computed hurdle would use `N_eff` (e.g. via clustering the trial return matrix). The
   ledger stores only compact stats, not return series, so `N_eff` is not computable without a
   schema change.

## Decision

**Keep the design; treat both guards as first-class and frame them honestly. No rework.**

- The purged + embargoed walk-forward is current best practice — leave it untouched.
- **PBO is now refreshed against the current ledger and shown as a primary metric** next to the
  champion DSR (chip + explainer), not an occasional afterthought. The explainer spells out the
  conceptual split: DSR validates the *single champion*; PBO validates the *selection process*.
- **A high, openly reported PBO is methodological integrity, not a failure.** The honest portfolio
  story is the *harness and the measurement*, not a deployable edge. Current measured PBO ≈ 0.77
  (top-13 configs, 8 CSCV blocks) → the search over this space is more likely finding luck than a
  durable signal, and we say so.

## Rejected (would be churn)

- **`N_eff` via trial-return clustering.** Genuinely the right fix for finding 2's leniency, but it
  needs the per-trial return series the ledger deliberately does not store (the compact-stats design
  is what lets the DSR be recomputed cheaply as N grows). Adding a return-matrix store + clustering
  is a real schema + compute change for a second-order correction — deferred, logged here, not built.
- A third overfitting metric or reworking the loop. The two correct tools are already implemented;
  the only real gap was framing PBO as primary, which is a display/copy change.

## Outcome

`scripts/run_pbo.py` re-run over the current champion set (PBO 0.686 → 0.77 as the search widened —
the expected direction). ResearchPanel explainer sharpened to state the DSR-vs-PBO distinction.
Champion at the time of writing: CatBoost on `(trend, breadth, mom_3m, vix)` — note `vix` is a live
FRED macro feature — DSR ≈ 0.998, Sharpe 1.10, MaxDD −9.3%, all OOS and deflated across 4100+ trials.
