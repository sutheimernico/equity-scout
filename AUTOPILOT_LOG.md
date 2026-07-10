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
- 2026-07-02 (10/10-hardening session, 7 tasks in one pass) — (1) Nikkei sectors: derived real
  industry sectors from the page's own h3 headings instead of hardcoded "Unknown" (222/223 live).
  (2) Actually ran refresh_universe.py — it was built for STOXX 600 + Nikkei 225 on 2026-06-26 but
  never re-run, so the committed CSV was still S&P-500-only (531: 503 US / 28 non-US) despite Phase 2
  being marked DONE for "real global universe"; now 1191 (503 US / 452 EU / 223 JP / 13 other).
  (3) Historized the universe in SQLite (`data/universe_storage.py`, as_of-keyed snapshots) so a
  refresh no longer silently overwrites what the universe looked like on past dates — survivorship
  bias avoidance for later backtest/ML use. (4) Hardened `ClaudeCliAnalysis`: checks the CLI's
  returncode now (a non-zero exit with stray stdout used to be silently adopted as the thesis); every
  failure mode degrades to an explicit "These nicht verfügbar (<reason>)". (5) Replaced fetch.py's/
  yf_provider.py's silent `except Exception` with logging + a thread-safe `FetchStats` counter and a
  new per-run `data_quality.py` report (fetch error rate, missing fundamentals, gate-filtered count),
  surfaced via `/api/latest` + a dashboard KPI tile. (6) Fixed a real backtest/forward inconsistency:
  `advance_account` let the strategy see today's own close before trading on it
  (`MarketView(panel, today + 1 day)`); the backtest engine never does this. Now exact boundary
  parity (`MarketView(panel, today)`). (7) ADR 0003: evaluated extending meta-labeling to the factor
  screener (qlib as reference) vs. splitting the ML loop into its own repo — kept status quo for both
  on stated grounds, flagged Rank-IC tracking as the correctly-scoped future step. 7 atomic commits,
  23 new tests (183 → 206), pytest + ruff green throughout, FE typecheck/build green. Branch
  autopilot/work. New dependency: none (stdlib `logging`/`threading` only).
- 2026-07-05 — Trading-Copilot Phase 1 (radar core) done interactively via subagent-driven flow:
  entry sub-signals (dip-quality/value-gap/momentum + static composite), entry zones + watchlist
  (zone-consistent notes, factor breakdown carried through), append-only signal_readings with
  watchlist FK (ML training seed), radar CLI + GET /api/radar. 11 commits, 220 → 241 tests,
  pytest + ruff green throughout; 2 live smoke runs (30 entries, 0 skipped); schema migration
  verified against live DB. Branch feat/trading-copilot-phase-1. New dependency: none.
  Spec: docs/superpowers/specs/2026-07-04-trading-copilot-design.md; next: Phase 2 (notifications/inbox).
- 2026-07-05 — Trading-Copilot Phase 2 (notifications & decision inbox) done interactively via
  subagent-driven flow: stdlib Telegram client (buy/pass/later one-tap, sender security gate),
  pitch builder (style breakdown + weakest-signal risk, Ollama seam + deterministic fallback),
  pitches lifecycle + cooldown storage, notify pipeline (in-zone/threshold/cooldown, resilient
  batch send, --dry-run), hardened long-poll receiver (backoff, self-healing edits), 24h-scoped
  e-mail digest, GET /api/inbox + decision POST. 10 commits, 241 → 284 tests, pytest + ruff green
  throughout; dry smoke created 2 real pitches from the live watchlist. Branch
  feat/trading-copilot-phase-2 (stacked on phase-1). New dependency: none. Needs Nico for live
  wiring: BotFather token + chat_id, SMTP creds. Next: Phase 3 (two-lane execution arena).
- 2026-07-05 — Trading-Copilot Phase 3 (two-lane execution arena) done interactively via
  subagent-driven flow: lane engine (rule-based exits target/stop/time + fixed-fraction buys,
  structured TradeRecord audit trail), lane persistence (portfolios + day-keyed valuations +
  append-only trade ledger doubling as the pitch-executed marker), arena runner advancing lane
  "nico" (approved pitches) and "autopilot" (score-autonomous) in one fair run (shared
  params/now/prices, SPY buy-and-hold benchmark), GET /api/arena. 8 commits, 284 → 305 tests,
  pytest + ruff green throughout; live smoke: autopilot bought EXE+EQT, nico idle (no approved
  pitch yet). Reviews on Opus 4.8 (Sonnet out of credits mid-phase). Branch
  feat/trading-copilot-phase-3 (stacked on phase-2). New dependency: none. Next: Phase 4 (ML
  entry-quality online learning) or Phase 6 (dashboard redesign — Radar/Inbox/Arena/Model).
- 2026-07-05 — Phase 4 done (entry-quality ML with honest online learning): price-derived
  backfill (no fundamentals → no look-ahead), relative-return labels vs SPY, purged date-grouped
  walk-forward OOS eval, versioned pickled model registry with strictly-better champion/challenger
  promotion, append-only predict-then-resolve prediction ledger + drift snapshot, train/score/
  resolve CLIs (network behind DI seams) and GET /api/model. The predict→resolve loop is CLOSED:
  run_score_watchlist logs live champion scores → run_resolve_predictions fills real outcomes
  (proved end-to-end by test_predict_resolve_loop_is_closed). Whole-phase review caught the loop
  half-wired (no production log_predictions caller) + a present-tense README overclaim on a public
  repo; both fixed. Renamed model_registry.champion → entry_champion (collision with ml.ledger).
  10 commits, 305 → 376 tests, pytest + ruff green throughout. Live smoke (10 tickers, 520 rows):
  OOS AUC 0.6195 / Brier 0.2424 / Rank-IC 0.1523 (n_oos=220, 2 splits), v1 promoted — above
  coin-flip but NOT a validated edge (small single-panel backfill; the now-populating ledger's
  resolved live outcomes are the real test). Reviews on Opus 4.8. Branch feat/trading-copilot-
  phase-4. New dependency: none. Next: Phase 5 (cron train/score/resolve) or Phase 6 (Model tab).
- 2026-07-05 — Phase 6 done (dashboard redesign — trading-terminal identity + four copilot
  surfaces): rewrote the index.css :root token block to a dark near-black blue-violet base with a
  phosphor-green signal + mono numerals, which reskinned the entire existing dashboard via CSS-var
  indirection (no per-component color edits); added a typed api.ts layer and four new surfaces —
  Radar (watchlist entry zones), Inbox (one-tap Kaufen/Ablehnen/Später pitches), Arena (Du vs
  Autopilot vs Markt equity race, the default view), Modell (champion metrics + resolved-prediction
  honesty) — plus ui/DisclaimerBar carrying each surface's German disclaimer. App shell nav leads
  with the copilot four (hairline separator) then the research four; key={view} reveal + responsive
  breakpoints kept. 8 commits, typecheck + build clean, 376 tests + ruff green (no Python changed);
  serve smoke: built dashboard served, /api/{radar,inbox,arena,model} all 200 on the live DB. Visual
  sign-off is Nico's per spec §8 (gate is liveness + data-shape only). Two contrast follow-ups
  flagged: white-on-accent in the Assistent chat (needs --on-accent token) and the .champion-glow
  legacy violet. Reviews on Opus 4.8. Branch feat/trading-copilot-phase-6. New dependency: none.
- 2026-07-07 fix: gate command `uv run pytest -q` was broken from clean checkout (9 collection errors — scripts/tests imports need repo root on sys.path); pinned pytest pythonpath=["."] — 408 tests green
- 2026-07-07 feat: congress-trades collector (kadoa monitor mirror, purchases only, filing-window bound) — live smoke 193 events; evidence store+ledger foundation shipped same day
- 2026-07-07 feat: EDGAR 13F collector (8 tracked funds, stateless two-filing diff) — live smoke 7/8 funds, 36 events, share-class dedup + stale-fund guard fixed after first live run
- 2026-07-07 feat: news-theme radar (Google News RSS + MarketWatch + Fed press, deterministic bigram counting, no LLM) — live smoke 130 headlines/3 feeds; unigram bar doubled after noise in first live run
- 2026-07-10 feat: evidence wired into notify path — pitches carry "Externe Signale" block (30d window, delay note), off-watchlist clusters (≥2 congress buyers or ≥2 funds) send labelled no-button alerts with 14d cooldown, row-before-send; 13 new tests
- 2026-07-10 feat: evidence ledger wired end-to-end — new run_evidence + run_resolve_evidence CLIs (store + predict-then-resolve vs SPY), /api/evidence edge monitor, digest per-source hit-rate section; 9 new tests
- 2026-07-10 feat: full automation glue — daily_copilot.sh chain (Mon: scout; radar→evidence→notify→score→resolve×2→lanes→digest, log-and-continue), receiver keepalive under flock, idempotent install_crontab.sh (crontab install itself = Needs Nico, permission-gated); live smoke: 223 events, 18 evidence alerts REALLY delivered via Telegram
