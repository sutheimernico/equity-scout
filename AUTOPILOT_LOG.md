# equity-scout — AUTOPILOT log (one line per iteration)

- 2026-06-24 — v1 vertical slice built interactively (not via loop): full funnel end-to-end,
  21 tests + ruff green, live yfinance run over 42 global tickers verified. Merged to main.
  AUTOPILOT integration added (PLAN.md/LOOP.md). Loop starts at Phase 2.
- 2026-06-24 — Phase 2 done (interactively): read-through cache, index-constituent sources
  (S&P 500 + curated CSV → 531-ticker combined universe, live-verified), retry/backoff +
  bounded-parallel fetch, gate stats by reason/region surfaced. 33 tests + ruff green.
  Follow-up logged: STOXX 600 + Nikkei 225 sources. Next: Phase 3 (scheduler + run history).
- 2026-06-24 — Phase 3 done (interactively): run-history (summaries, /api/history, churn helper,
  dashboard section), budget-capped LLM theses (--llm-top-n), scheduled_run.sh + scheduling docs
  (cron + systemd templates). 37 tests + ruff green. Next: Phase 4 (factor/bucket refinement).
- 2026-06-24 — Phase 4 done (interactively): fixed value-factor bug (non-positive P/E no longer
  "cheap"), sector-relative ranking, low-volatility factor, docs/factors.md. Winsorize dropped as
  no-op for rank-based scoring. 42 tests + ruff green; live run shows buckets now well-differentiated
  (defensive=staples/quality, aggressive=momentum/growth). Next: Phase 5 (React dashboard).
- 2026-06-24 — Phase 5 done (interactively): Vite + React 19 + TS dashboard (bucket tabs, score
  bars, region filter, drilldown), FastAPI serves built dist/. typecheck + build green, 42 py tests
  + ruff green, live server verified (index/asset/api all 200). All five planned phases complete.
- 2026-06-24 — Phase 6+7 (new loop, Nico's feedback): full FE redesign (Geist/Linear dark token
  system, app shell + KPI tiles + underline tabs, modular components, descriptive names) + score
  transparency (API exposes bucket_weights; card drilldown shows percentile×weight=contribution;
  in-app methodology note). typecheck+build+42 py tests+ruff green, live verified. Next: Phase 8
  (paper-trading bot) + backend naming cleanup.
- 2026-06-24 — Phase 8 + naming cleanup done: paper-trading bot (Portfolio model, buy-and-hold over
  threshold, mark-to-market vs SPY benchmark + fee, persisted; run_paper.py + /api/portfolio +
  dashboard portfolio view), live-verified (9 positions bought). Backend var-name cleanup in
  factors/gate/buckets. 50 py tests + ruff + FE typecheck/build green.
- 2026-06-26 — Phase 2 follow-up done: STOXX Europe 600 + Nikkei 225 constituent sources behind the
  ConstituentSource seam. STOXX maps bare ticker + Country -> Yahoo symbol via country->exchange
  suffix map (459/600 mapped live across 15 exchanges; unmappable countries skipped, not guessed).
  Nikkei tag-strips the sector-bulleted page then code+.T (223/225 live). 6 new pure-parse tests.
  175 pytest + ruff green. Branch feat/auto-research-ml-loop.
- 2026-06-26 — Phase 5 follow-up done: screener sector filter (chains with region, resets on bucket
  switch) + GatedOutList disclosure surfacing the data-completeness gate (excluded tickers + reasons,
  filterable by reason, per-region summary). typecheck + vite build green; live-verified vs the API
  (gated_out + sectors populated). Branch feat/auto-research-ml-loop.
- 2026-06-26 — Phase 8 follow-up done: screener paper bot gains rule-based exits (hysteresis: buy
  >=0.70, sell <0.55 or drop-out; missing price defers the sale), slippage on each fill + commission
  (churn costs money), and a valuation-vs-benchmark sparkline (reused EquityChart). run_paper.py gets
  --exit-threshold. 5 new tests; 180 pytest + ruff green; FE typecheck/build green; fake-provider
  smoke ok. Branch feat/auto-research-ml-loop.
- 2026-06-26 — Headline ML loop verified complete + phase self-challenge. CatBoost (3rd learner),
  FRED features (vix/term_spread, free CSV no key), rising-DSR hurdle, per-bet attribution (logged +
  rendered in MLPanel), and the live Auto-Research tab are all built and live-verified against a
  4100+ trial ledger. Champion: CatBoost on (trend, breadth, mom_3m, vix), DSR 0.998 / Sharpe 1.10 /
  MaxDD -9.3% OOS. Sourced overfitting challenge (Bailey & LdP) -> ADR 0002: PBO made first-class +
  framing sharpened, N_eff-clustering rejected as churn. PBO refreshed 0.69->0.77. 180 pytest + ruff
  + FE typecheck/build green. Branch feat/auto-research-ml-loop.
- 2026-07-01 (autopilot loop) — Closed the last open Phase F item: /api/ml now serves the research
  loop's current champion config (ml/ledger.champion) instead of always the fixed baseline, falling
  back gracefully when no ledger/champion exists yet. 2 new tests (build_ml_report with a custom
  config; /api/ml end-to-end with a seeded champion). 187 pytest + ruff + FE typecheck/build green.
  Also reconciled stale plan checkboxes (Phases A/B-orig/C-orig/D-orig/E-orig) with what the codebase
  and Outcome notes actually show — several were fully shipped or superseded but left unchecked,
  which nearly caused this iteration to duplicate already-done work. Branch autopilot/work.
