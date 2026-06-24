# equity-scout — Plan (AUTOPILOT-driven build backlog)

**Source of truth for design:** `docs/superpowers/specs/2026-06-24-equity-scout-design.md`
**v1 implementation log:** `docs/superpowers/plans/2026-06-24-vertical-slice-v1.md` (done — see Outcome).
Personal rules (`~/.claude/CLAUDE.md`) + global loop rules (`~/private/AUTOPILOT.md`) apply.

> **NEXT MAJOR DIRECTION (2026-06-24) — IN PROGRESS:** multi-strategy paper-trading (N strategies as
> N demo accounts, dashboard tabs) + a self-learning ML meta-model with a feedback loop.
> **Active plan + phase backlog: `docs/superpowers/plans/2026-06-24-multi-strategy-v2.md`**
> (Phases A–F). Research + resolved §9 decisions: `docs/research/2026-06-24-strategy-ml-data-research.md`.
> Vision: `docs/superpowers/specs/2026-06-24-multi-strategy-ml-vision.md`. The phases below
> (Phase 2–8 + redesign/transparency/paper/naming) are the prior, completed v1 work.
>
> Key research findings that changed the spec: (1) the TAA family (Faber GTAA, VAA, **DAA**, PAA,
> Accelerating DM) + Permanent/All-Weather benchmarks were the biggest gap — added to v1.
> (2) Intraday is a dead end on free data — dropped. (3) `mlfinlab` is no longer open-source — use
> `purgedcv`/`skfolio`/CatBoost. (4) Backtest history is the initial ML training material; forward
> paper is the feedback loop — backtest and forward share one engine.

This file is the binding backlog for the autonomous loop. Each iteration picks the SINGLE
highest-value open `- [ ]` task, does it on `autopilot/work`, runs the gate, commits only if green,
checks the box, and appends one line to `AUTOPILOT_LOG.md`.

## Iron principles (never overridden)
- **Local & free only.** yfinance / SEC EDGAR (UA header) / public lists. No paid feeds, no
  real-money anything. A task needing a paid resource goes to "Needs Nico", never faked.
- **Honesty guardrails on every surface.** Disclaimer present; LLM theses are interpretation,
  never price forecasts; the data-completeness gate is mandatory — never rank thin-data noise.
- **Gate is objective:** `uv run pytest -q` green AND `uv run ruff check .` clean. Never commit red.
- **Small, reviewable diffs.** New logic ships with a test. Net/LLM behind seams, faked in tests.
- **One change per iteration.** No bundling. No speculative abstractions (YAGNI).

## Status
- **v1 Vertical Slice — DONE.** Funnel end-to-end (universe→data→gate→factors→buckets→LLM-seam→
  SQLite→API→dashboard), 21 tests + ruff green, live yfinance run over 42 global tickers verified.

## Phase 2 — Persistent cache + real global universe — DONE (2026-06-24)
- [x] Read-through SQLite quote cache (`data/cache.py`), freshness vs. injected run-date, wired into CLI.
- [x] Index-constituent sources behind a seam (`data/constituents.py`): hand-curated global CSV +
      S&P 500 from Wikipedia (polite UA), deduped → `data/universe_combined.csv` (531) + provenance.
- [x] Retry/backoff + bounded-parallel fetch (`data/fetch.py`), wired into pipeline + yfinance provider.
- [x] Per-run gate statistics (total, by reason, by region) persisted + surfaced in API + dashboard.
- [ ] Follow-up: add STOXX Europe 600 + Nikkei 225 constituent sources (each needs an exchange→Yahoo
      suffix mapping; Nikkei is `code + .T`, STOXX is multi-exchange). v2.2 shipped S&P 500 only.

## Phase 3 — Scheduler automation + run history — DONE (2026-06-24)
- [x] `scripts/scheduled_run.sh` + `docs/scheduling.md` (cron + systemd user-timer templates).
- [x] Run-history: `load_run_summaries`, `/api/history`, `pick_churn` helper, dashboard history section.
- [x] Budget-capped LLM theses: `attach_theses(max_per_bucket)` + CLI `--llm-top-n` (default 3).

## Phase 4 — Factor / bucket refinement — DONE (2026-06-24)
- [x] Sector-relative percentile ranking for value/quality/growth (momentum/low-vol stay global).
- [x] Low-volatility factor (stdev of daily returns), wired into bucket weights (defensive 0.25).
- [x] ~~Winsorize~~ → replaced by **cleaning invalid values** (non-positive P/E/P/B dropped).
      Rank-based scoring is ordinal, so winsorizing is a no-op; cleaning was the real fix.
- [x] `docs/factors.md` — families, directions, sector-relative + rank-based rationale, weights,
      honest limitations.

## Phase 5 — Dashboard polish (React) — DONE (2026-06-24)
- [x] Vite + React 19 + TS dashboard (`frontend/`): bucket tabs, score-breakdown bars, region
      filter, per-pick drilldown (factor bars + thesis). FastAPI serves the built `dist/`.
- [x] Gate stats (total + by region) + disclaimer surfaced; run-history section.
- [ ] Follow-up: sector filter (region done) and a dedicated gated-out list view.

## Phase 6 — Frontend redesign — DONE (2026-06-24)
- [x] Dark design-token system (Geist/Linear-style: near-black surface stack, border-as-shadow,
      one accent, tabular-nums).
- [x] App shell: topbar + KPI stat-tiles + underline tabs + responsive card grid.
- [x] Redesigned pick cards, score bars, history as a clean hairline table; modular components
      with descriptive names (StatTile/PickCard/RunHistory/MethodologyNote, format.ts helpers).

## Phase 7 — Score transparency — DONE (2026-06-24)
- [x] API exposes `bucket_weights`; pick drilldown shows per-factor `percentile × weight =
      contribution`, composite = sum of contributions.
- [x] In-app methodology note explaining rank-based, sector-relative scoring + the data gate.

## Phase 8 — Paper-trading bot — DONE (2026-06-24)
- [x] Paper portfolio (100k demo): buy picks with composite ≥ threshold, equal-weight, buy-and-hold;
      mark-to-market vs cost + SPY benchmark, small fee; persisted (portfolio + valuation history).
- [x] `scripts/run_paper.py` to advance it + `/api/portfolio` + dashboard portfolio view. Paper-only.
- [ ] Follow-up: sell/exit rules, costs/slippage realism, valuation sparkline chart.

## Code quality — DONE (2026-06-24)
- [x] Renamed cryptic variables (fam, _t closure trick, t/q/pct, s) to descriptive names in
      factors/gate/buckets; frontend uses descriptive names throughout. Behavior unchanged, tests green.

## Standing mandate (per AUTOPILOT, once per phase — not per iteration)
- [ ] Research current best practice (factor investing, free data sources, screening pitfalls) and
      challenge this plan. If a materially better approach exists, write an ADR in `docs/adr/` and
      adjust the backlog. Re-examine settled decisions only with a concrete, sourced reason.

## Needs Nico (loop cannot do these itself)
- Git remote / visibility decision before any first push (repo is currently local-only).
- Any data source that would require a paid key (do NOT sign up — log here instead).
