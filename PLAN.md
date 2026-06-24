# equity-scout — Plan (AUTOPILOT-driven build backlog)

**Source of truth for design:** `docs/superpowers/specs/2026-06-24-equity-scout-design.md`
**v1 implementation log:** `docs/superpowers/plans/2026-06-24-vertical-slice-v1.md` (done — see Outcome).
Personal rules (`~/.claude/CLAUDE.md`) + global loop rules (`~/private/AUTOPILOT.md`) apply.

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

## Phase 4 — Factor / bucket refinement
- [ ] Sector-relative percentile ranking (rank within sector) to remove sector bias; document why.
- [ ] Add a low-volatility factor and wire it into the defensive bucket weighting.
- [ ] Winsorize/clip raw metrics before ranking to blunt outliers; unit-test the clipping.
- [ ] Document factor definitions + rationale in `docs/factors.md`.

## Phase 5 — Dashboard polish (React)
- [ ] Migrate the vanilla page to React 19 (reuse signal-trader dashboard patterns): bucket tabs,
      score-breakdown bars, region/sector filters, per-pick drilldown.
- [ ] Surface the gated-out list + data caveats prominently in the UI.

## Standing mandate (per AUTOPILOT, once per phase — not per iteration)
- [ ] Research current best practice (factor investing, free data sources, screening pitfalls) and
      challenge this plan. If a materially better approach exists, write an ADR in `docs/adr/` and
      adjust the backlog. Re-examine settled decisions only with a concrete, sourced reason.

## Needs Nico (loop cannot do these itself)
- Git remote / visibility decision before any first push (repo is currently local-only).
- Any data source that would require a paid key (do NOT sign up — log here instead).
