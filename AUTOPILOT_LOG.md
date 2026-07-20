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
- 2026-07-10 feat: person track-record scoring — kadoa per-filer backfill (977 calls/13 filers live), own-methodology abnormal returns vs SPY (1M/3M, n>=5 gate, 540d recency decay), person_scores table + /api/evidence, track-record lines on pitches/alerts, single strong buyer (>=+2% @3M) alerts alone; live: 5 scoreable persons (Peters +7.2%, Whitehouse +4.3%, Trump -6.7%); fixed dead-ticker clean_panel crash + column-wise load_price_history + BRK.B->BRK-B mapping; 22 new tests
- 2026-07-11 fix: review finding — scoreable gated on the SHORT horizon while the note renders LONG-horizon fields, so a fresh buyer (all calls 21-62 trading days old) got a fabricated "0 % Treffer 3M"; gate now counts 3M-resolvable calls, attach_track_records additionally requires measured fields, `or 0` coalescing removed; live rescore: Peters correctly gated (5 calls all <3M old), Whitehouse stays strong (n=18); 2 regression tests
- 2026-07-13 feat: voices evidence source — Google/Bing News RSS person queries for the 8 tracked fund managers; deterministic call/context boundary (name-before-verb + unambiguous ticker), bullish calls -> ledger + person track record, bearish calls display/alert only, mentions context-only; live smoke 184 mentions -> 1 bearish call + 11 context; 22 new tests
- 2026-07-13 feat: entry model v2 — OOS isotonic calibration (never in-sample), catboost + soft-voting ensemble presets, run_train_entry trains ALL presets by default (hardened gate alone promotes), --horizon param + SHORT_HORIZON_DAYS=10 for the bots; docstring cron-lie fixed; 5 new tests
- 2026-07-14 feat: ML bot family — signed weights (TargetWeight.side, gross-exposure guard), short P&L + borrow-cost proxy + simulated margin floor in forward paper, registry partitioned by family (entry/entry_short, own champions), short model trains on inverted lags-label @10d horizon, MLLong/MLShort strategies (whitelist shorts) wired into run_forward_paper; live smoke: Long Bot trades (champion existed), Short Bot honestly skipped; 14 new tests
- 2026-07-14 feat: visible learning curve — champion_history table written on every promotion, resolved_stats_windowed (30/90d rolling), training feature_means registered so /api/model serves a REAL drift snapshot (was a None placeholder), new /api/model/history (per-family version curve + promotion timeline); hurdle-per-trial moved to backlog (positional-INSERT ledger rework); 4 new tests
- 2026-07-14 feat: always-on operation — intraday_copilot.sh every 30 min inside a tested Berlin-time US-market-window guard (radar + fast evidence congress/news/voices via run_evidence --fast + notify), nightly_train.sh 02:30 Tue-Sat (all presets both families + 25-trial research batch + forward paper), install_crontab.sh extended idempotently, every pitch now states the ~15-min yfinance price delay; crontab install stays Needs Nico; 5 new tests
- 2026-07-14 feat: IA overhaul — grouped nav with visible labels (Heute | Signale: Screener/Radar/Stimmen | Entscheiden: Inbox/Depots | Forschung: Strategien/Entry-Modell/Signal-Filter/Lernkurven | Assistent), Heute start page, ALL paper depots unified under Depots with TimeContextBadge (kills the Live(Forward) ambiguity), Modell/Meta-Modell naming collision resolved, VoicesPanel, LearningCurvePanel (AUC per generation + promotions + rolling hit-rate), per-ticker SignalStackBlock in radar (lazy /api/stack/{ticker}), ML score joined into /api/radar; backend: /api/stack, latest_scores; FE typecheck+build green, 507+ tests
- 2026-07-14 feat: nav moved to a fixed left sidebar (Nico wish, v6.1) — vertical grouped nav with labels, sticky, falls back to a top bar under 720px; typecheck+build green, served live
- 2026-07-14 feat: universe v3 — NASDAQ Trader symbol directory source (free, keyless): all US-listed common stocks incl. ADRs, deterministic non-common filters; sector backfill from yfinance info for Unknown-sector names; live refresh: 6592 instruments (was 1191); 3 new tests
- 2026-07-14 fix: first 6.6k-universe scout run died twice — (1) factors._clean crashed on yfinance string values in numeric fields (now honest None for non-numeric/non-finite), (2) 8-worker fetch hammered straight through Yahoo rate limits (with_retry now backs off 30s/60s on rate-limit errors, scout default 4 workers); 3 new tests; rerun resumes via read-through cache
- 2026-07-14 fix: closed-end funds (no ETF flag in the directory) polluted the first 6.6k screen — 'funds?' added to the non-common name filter (Calamos CEFs out, REIT common stock stays); universe 6592 -> 6318; scout re-run from cache
- 2026-07-15 A1: paper sizing now from current equity (portfolio+lanes), 4 regression tests (6a8b2d0)
- 2026-07-15 A3: triple-barrier entry_tb family, barrier config persisted + horizon single-source fix (e4134c7, 26ba882)
- 2026-07-16 v8/A1: telegram_client speaks optional HTML parse_mode (escape_html/strip_html, parse-failure plain-text retry on every send/edit path); builders opt in via A3/A6
- 2026-07-16 v8/A2: at-a-glance verdict (green/yellow/red + why) computed once, persisted on the pitch row, rendered on caption, long pitch, inbox API and dashboard badge
- 2026-07-16 v8/A3: caption + long pitch reworked to Telegram HTML paragraph layout (bold head/verdict, escaped dynamics, expandable detail quote in text variant only, safe overflow degradation)
- 2026-07-16 v8/A4: top-up quality gate (extras never below --threshold), honest one-line empty-day telegram note, below-threshold transparency in run_notify output
- 2026-07-16 v8/A5: detail button (detail:<id>) on every pitch keyboard; receiver replies with persisted HTML long pitch (pitch_html column, shared cached ollama call), press never decides
- 2026-07-16 v8/C1: regime.py market traffic light (trend/vix/breadth/yield-curve, green-count composite, honest unknown below 3 evaluable signals), 9 tests
- 2026-07-16 v8/B1: SectorRotationStrategy (11 SPDR sector ETFs, top-3 by 12m/6m momentum blend, per-slot absolute-momentum hurdle to IEF, young tickers skipped) registered; ETF panel grows to 21 tickers
- 2026-07-16 v8/B3: sector momentum snapshot (sectors.py, same MarketView math as the rotation) + /api/sectors + Sektoren card on the strategies dashboard; ETF_NAMES/STRATEGY_PITCH extended
- 2026-07-16 v8/A6: digest head shows market traffic light + top-3 sectors + below-threshold transparency; HTML variant (bold heads, escaped, split-safe) for telegram, plain for SMTP/stdout
- 2026-07-16 v8/B2: verified sector rotation flows into forward paper + dashboard via the shared registry; integration tests incl. stale pre-v8 panel staying defensively in bonds
- 2026-07-16 v8/C2: /api/regime (day-cached, per-leg degradation) + RegimeCard on Today view; breadth = sector-ETF approximation labelled as such; digest regime now uses it too
- 2026-07-16 v8/D1: 52-week-high proximity (info fiftyTwoWeekHigh, zero extra fetches) as second momentum metric; cache schema tolerant of pre-v8 rows; docs/factors.md updated
- 2026-07-16 v8/D2: Piotroski F-Score from EDGAR XBRL companyfacts (watchlist-only, 30d cache, honest per-criterion None, min 5 evaluable) as standalone balance-trend line on pitch surfaces; run_fscore.py in daily chain; NOT in the universe quality blend (documented deviation)
- 2026-07-20 v9/Q5 Befund: nightly `n_oos=0, Splits=0` für ALLE Presets ist Datenmangel, kein Bug — die Split-Einheit sind unique monatliche as_of-Stichtage (rebalance_dates), nicht Zeilen; das reale entry_panel (ab 2025-02, 370 Handelstage) liefert nach MIN_HISTORY-Anlauf (252d) + Horizon-Cropping nur 4 Stichtage (120 Zeilen / 30 Ticker), purged_walk_forward braucht min_train+n_splits = 28 → 0 Folds. Fix: ehrliche Hinweis-Zeile im Trainer-Output (Ursache + Abhilfe = mehr Panel-Historie); Registrierung bleibt (bestehender Vertrag: Challenger sammeln, Promotion-Gate schützt), Split-Parameter bleiben strikt; 1 neuer Test
- 2026-07-20 v9 komplett (Tasks 11–18): butler.py Monats-Sparplan (Mix-Gewichte → ganze EUR, 80/20 Kern/Satellit, Monats-Gating via app_state, Overhang-Fix), 0-Pitch-Tage nennen die richtige Inaktion + 5%-Positionsregel im Tranchen-Block, Faktor-Köpfe als Wörter statt Ranks + Tap-Hinweis vor expandable Quote, SEC-Throttle 0.15s + non-XML-Sanity-Check, F-Score insufficient≠failed, nicht-US-Ticker raus aus dem CIK-Gap-Zähler (beide Collector); 941 Tests; LIVE: erster echter v9-Lauf 18:02 (Digest + Monats-Block zugestellt), systemd-18:05-Trigger sauber arbitriert; Windows-Task-Registrierung = Needs Nico
2026-07-20: vision v10 autotrader — meta-allocated risk-managed paper auto-depot (allocator, protections, engine, storage, runner, nightly step, digest/api/fe), 997 tests, live-smoked incl. concentration-cap fire + idempotency
2026-07-20: v10.1 always-on — nightly guard wrapper + persistent systemd timer (installed) + crontab switch + windows task XML; auto-depot track record survives missed slots; 1000 tests
2026-07-20: v11 kurzfrist-arena — 3 lanes (swing/session/crypto) + arena surfaces; session lane live-traded Monday session (7 fills), overnight-sweep gap found+fixed+live-proven; 1042 tests
- 2026-07-20 v12 R1: session lane force-flats stale positions before decide (P0 review fix), 2 tests
- 2026-07-20 v12 R2: central db.connect (WAL + busy_timeout 30s) adopted by autotrader+shortterm storage, 2 tests
- 2026-07-20 v12 R3: persist_advance = one transaction (valuation/trades/events + account blob last), crash-rollback test
- 2026-07-20 v12 R4: persist_lane_step = one transaction for all four lane callers, crash-rollback test
- 2026-07-20 v12 R5: depot mirrors ML sleeves' post-exit books (sleeve_holdings seam), false docstring fixed, 3 tests
- 2026-07-20 v12 R6: pending digest persisted on TelegramError, */15 notify chain resends same-day exactly once, 2 tests
- 2026-07-20 v12 R7: digest warns on stale autodepot as_of (busdays>2) and stale lanes (crypto calendar>1), 4 tests
- 2026-07-20 v12 R8: ensure_new_york_tz in fetch_bars (loud IntradayDataError on naive index), 3 tests
- 2026-07-20 v12 R9: return-frame drops >4-calendar-day gap observations, 1 test
- 2026-07-20 v12 R10: market window = NYSE 09:30-16:00 +30min grace in market tz (DST-transition weeks covered), 6 tests
- 2026-07-20 v12 R11: /api/entry fetch guard, rejected-callback acks, swing 3-busday event cutoff + README, 3 tests
- 2026-07-21 v12 W1: heartbeats (daily/nightly/crypto/watchdog) + run_watchdog alarm w/ 24h cooldown, crontab updated live, 6 tests
- 2026-07-21 v12 W2: push_events (silent, env-gated COPILOT_TG_AUTOTRADER_EVENTS) after nightly advance, 2 tests
