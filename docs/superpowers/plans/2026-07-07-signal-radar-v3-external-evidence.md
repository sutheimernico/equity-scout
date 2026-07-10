# Signal-Radar v3 — External Evidence + Full Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (this plan is
> being executed inline in the authoring session; a fresh loop iteration picks up open
> checkboxes task-by-task). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The copilot chain runs fully unattended (cron) and pitches carry — plus alert on —
external evidence: US-congress trades, 13F moves of tracked famous funds, and cross-source
news themes, each honesty-tracked in its own predict-then-resolve ledger.

**Architecture:** A new `src/equity_scout/evidence/` package with one collector per source
behind a fetch seam (faked in tests), a shared SQLite `evidence_events` store (append-only,
idempotent via event keys), an `evidence_ledger` mirroring `ml/prediction_ledger.py`
(append-only, predict-then-resolve, stats per source), and a pitch/notify integration that
ANNOTATES — the proven entry composite and selection rules stay untouched. Automation is a
cron-driven shell chain where every step degrades independently (one dead source never kills
the run).

**Tech Stack:** httpx + stdlib `xml.etree` (no new deps), SQLite, existing Telegram client,
cron. LLM (Ollama) labels/interprets only — it never ranks, scores, or forecasts.

**Go given by Nico in-session 2026-07-07 ("mach das mal alles nach bestem Gewissen").**

---

## Source decisions (research 2026-07-07, live-verified by research agent)

| Source | Verdict | Endpoint | Caveats |
|---|---|---|---|
| Senate/House Stock Watcher S3 | **dead** (403, unmaintained since 2021) | — | do not use |
| Congress trades: `kadoa-org/congress-trading-monitor` | **use** | raw JSON via `raw.githubusercontent.com` (MIT, refreshed daily, House+Senate+OGE since 2012) | ticker mapping gaps on non-stock assets; amounts are ranges only; §105(c) STOCK Act limits *commercial* use — fine for this private local tool, re-check before any publication |
| SEC EDGAR 13F / submissions | **use** | `data.sec.gov/submissions/CIK{10}.json` → accession → index → INFORMATION TABLE XML | UA header with contact REQUIRED (else 403 + temp IP block), ≤10 req/s (we stay far below); info-table filename is not fixed — discover via index |
| Yahoo Finance RSS | **dead** (discontinued 2024) | — | per-ticker news stays on `yf.Ticker(...).news` |
| Google News RSS | **use** | `news.google.com/rss/search?q=...&hl=en-US&gl=US&ceid=US:en` | undocumented, may break — never a hard dependency; personal use only |
| MarketWatch RSS + Fed press feed | **use** (redundancy / deterministic macro events) | `feeds.content.dowjones.io/public/rss/mw_topstories`, `federalreserve.gov/feeds/press_all.xml` | — |

**Finfluencer/"guru" channels (YouTube/X) are deliberately OUT:** research shows
post-publication picks underperform on average, scraping violates platform ToS, and the same
"what are famous investors doing" intent is served legally and structurally by the 13F
collector. Recorded here so a later iteration doesn't re-add them without a sourced reason.

**EDGAR contact UA:** read from env `EDGAR_USER_AGENT`; when missing the 13F collector reports
itself `unconfigured` and the chain continues (leitstand pattern — never fake, never block).
Documented in `.env.example`; setting it in `.env` is a Needs-Nico one-liner.

**CUSIP→ticker:** 13F info tables carry CUSIP + issuer name, no ticker. Free CUSIP maps don't
exist; we match normalized issuer names (upper-case, strip INC/CORP/PLC/LTD/…) against the
universe's company names. Unmatched holdings are reported by name and counted — honest gap,
never guessed.

## Honesty guardrails (extend the iron principles, never overridden)

- Evidence NEVER changes the entry composite, selection threshold, or bucket weights. It
  annotates pitches and may trigger a **separately labelled** alert type.
- Every pitch/alert surface states the structural delay: congress disclosures up to 45 days,
  13F up to 135 days after quarter end — "Kontext, kein Frühsignal".
- Every collected evidence event is logged to the evidence ledger BEFORE its outcome is
  knowable and resolved later against real forward prices (mirror of `prediction_ledger`).
  Per-source hit-rates are queries, not promises.
- Collectors degrade to explicit skip reasons (`unconfigured`, `fetch_failed`, `parse_failed`)
  — an empty result is always distinguishable from a dead source.

## File structure

- Create: `src/equity_scout/evidence/__init__.py` (empty marker)
- Create: `src/equity_scout/evidence/base.py` — shared `CollectorResult` dataclass
  (`source`, `status: "ok" | "unconfigured" | "fetch_failed" | "parse_failed"`, `events`,
  `detail`) used by every collector
- Create: `src/equity_scout/evidence/congress.py` — `CongressTrade` dataclass,
  `parse_congress_trades(payload) -> list[CongressTrade]` (pure),
  `fetch_congress_trades(http_get) -> CollectorResult`
- Create: `src/equity_scout/evidence/edgar.py` — `TRACKED_FUNDS: dict[str, str]` (name→CIK,
  ~8 curated funds), `Holding`/`Filing13F` dataclasses, `fetch_latest_13f(cik, http_get)`,
  `diff_13f(current, previous) -> list[PositionChange]`, name-normalization matcher
- Create: `src/equity_scout/evidence/news_themes.py` — `Headline` dataclass, feed parsers
  (stdlib XML over RSS/Atom), `detect_themes(headlines, ...) -> list[Theme]` (deterministic
  token/bigram counting, stopword list, ≥N headlines from ≥M distinct sources), optional
  Ollama `label_theme` (label only, fallback = raw keyword)
- Create: `src/equity_scout/evidence/storage.py` — `evidence_events` table (append-only,
  UNIQUE event key per source), `record_events`, `evidence_summary(db, tickers, window_days,
  now)`, `off_watchlist_clusters(db, exclude_tickers, window_days, now)`
- Create: `src/equity_scout/evidence/ledger.py` — `evidence_predictions` table
  (source column), `log_evidence`, `due_evidence`, `resolve_evidence`, `stats_by_source`
- Create: `src/equity_scout/evidence/aggregate.py` — `evidence_block(summary) -> str | None`
  (German "Externe Signale" pitch block incl. delay disclaimer),
  `select_evidence_alerts(clusters, min_congress_buys=2, min_funds=2)` + alert text builder
- Create: `scripts/run_evidence.py` (collect+store+ledger-log), `scripts/run_resolve_evidence.py`
- Create: `scripts/daily_copilot.sh` (cron chain), receiver keepalive via `flock` cron line
- Modify: `src/equity_scout/pitch.py` (optional `evidence` arg → block between Kennzahlen and
  Analystensicht), `scripts/run_notify.py` (load summaries, pass through; send evidence alerts),
  `src/equity_scout/notify.py` (alert path), `src/equity_scout/api.py` (+`/api/evidence` stats),
  `scripts/run_digest.py` (per-source ledger stats section), `docs/scheduling.md`, `.env.example`
- Tests: `tests/test_evidence_congress.py`, `tests/test_evidence_edgar.py`,
  `tests/test_evidence_news_themes.py`, `tests/test_evidence_storage.py`,
  `tests/test_evidence_ledger.py`, `tests/test_evidence_aggregate.py`, extensions to
  `tests/test_pitch.py` / `tests/test_notify.py` / `tests/test_api.py`

## Task backlog

### Task 0 — Baseline gate + branch hygiene — DONE 2026-07-07
- [x] ff `autopilot/work` to pitch-v2 tip; track `docs/sessions/`
- [x] Gate was RED from clean checkout (9 collection errors): documented command
      `uv run pytest -q` lacked repo root on sys.path → pinned `pythonpath = ["."]`,
      408 tests green + ruff clean, committed.

### Task 1 — Evidence storage + ledger (foundation)
- [ ] `evidence/storage.py` + tests: append-only events, idempotent re-record (same event key
      → no duplicate), summary windows by ISO date math (injected `now`, no wall clock)
- [ ] `evidence/ledger.py` + tests: mirror `ml/prediction_ledger.py` semantics (append-only,
      single open→resolved transition, stats over resolved rows only, per-source split)
- [ ] Gate green → commit each module separately

### Task 2 — Congress collector
- [ ] Discover the monitor repo's raw JSON layout live (GitHub API/raw); pin file URL(s) as
      module constants with a comment carrying the discovery date
- [ ] Pure parser + dataclass + tests (fixture JSON snippet, purchase/sale mapping, range
      amounts, missing-ticker rows skipped and counted)
- [ ] Fetch seam (httpx, timeout, explicit CollectorResult status) + `scripts/run_evidence.py`
      first wiring; live smoke run against the real raw URL (allowed: free, MIT)
- [ ] Gate green → commit

### Task 3 — EDGAR 13F collector
- [ ] Submissions→accession→index→info-table walk behind one `http_get` seam; stdlib XML,
      namespace-tolerant; tests on fixture XML (incl. filename discovery via index JSON)
- [ ] Quarter diff (new / increased ≥25% shares / closed) + issuer-name→universe matcher +
      tests (unmatched counted, never guessed)
- [ ] `run_evidence.py` wiring incl. `unconfigured` skip without `EDGAR_USER_AGENT`;
      `.env.example` line; live smoke only if UA configured — else log Needs Nico
- [ ] Gate green → commit

### Task 4 — News-theme radar
- [ ] RSS/Atom parse (stdlib) for Google News search feeds + MarketWatch + Fed press; tests on
      fixture XML; per-feed independent failure
- [ ] `detect_themes`: deterministic counting (stopwords, bigrams first, min_hits=3,
      min_sources=2) + tests; optional Ollama label via existing `chat.ask_ollama` seam
      (interpretation only, fallback = keyword) + contract test
- [ ] Ticker attach: watchlist tickers whose own `yf` headlines contain a detected theme token
      → `news_theme` evidence event; tests
- [ ] Gate green → commit

### Task 5 — Aggregation into pitches + evidence alerts — DONE 2026-07-10
- [x] `evidence_block` German text (counts + recency + delay disclaimer);
      `build_pitch(entry, fundamentals, evidence=None)` inserts block between Kennzahlen and
      Analystensicht; tests extend test_pitch
- [x] Evidence alerts: off-watchlist clusters (≥2 distinct congress buyers in 30d OR ≥2 tracked
      funds newly in) → clearly labelled "🔎 Evidenz-Alarm — kein Screener-Pick" Telegram text
      with SHORT_DISCLAIMER + delays. DEVIATION from plan: alerts do NOT reuse inbox
      `create_pitch` — they live in their own `evidence_alerts` table because the inbox schema
      has NOT-NULL price/zone/composite columns that alerts would have to fake; own 14-day
      cooldown (facts accumulate slowly), row-before-send, no decision keyboard; tests
- [x] `run_notify.py` wiring (evidence summaries for candidates via build seam; alerts after
      pitches; alert sender without keyboard)
- [x] Gate green → commit

### Task 6 — Ledger wiring + edge monitor — DONE 2026-07-10
- [x] `run_evidence.py` (NEW — Tasks 2–4 had only live-smoked the collectors ad hoc):
      collect all three sources, store, ledger-log ONLY newly inserted events (horizon 60d);
      `run_resolve_evidence.py` resolves due rows against real forward prices (mirror of
      `run_resolve_predictions.py`, own resolve snapshot); tests with fake collectors/panel
- [x] `/api/evidence` (30d events + recent alerts + per-source resolved stats) + digest
      section "Evidenz-Quellen — gemessene Trefferquote vs SPY"; tests
- [x] Gate green → commit

### Task 7 — Automation glue (the missing "läuft von allein") — DONE 2026-07-10 (crontab install = Needs Nico)
- [x] `scripts/daily_copilot.sh`: source `.env` if present, then (Mondays: scout) → radar →
      evidence → notify → score_watchlist → resolve_predictions → resolve_evidence → lanes →
      digest, each step log-and-continue, all output appended to `copilot.log`; uses
      `.venv/bin/python` directly (cron PATH has no uv) — `scheduled_run.sh` switched too
- [x] Weekly screener wrapper (scout Mondays before the daily chain, `date +%u` branch)
- [x] Receiver keepalive via `flock -n` (`scripts/receiver_keepalive.sh`: single instance,
      quiet no-op without Telegram env)
- [x] Crontab: `scripts/install_crontab.sh` (idempotent, preserves existing lines) — the
      sandbox permission layer blocked modifying the crontab from the autonomous session,
      so INSTALLING it is a one-liner in Needs Nico; `docs/scheduling.md` documents the
      exact lines + WSL caveat
- [x] Live smoke 2026-07-10: full chain end-to-end green — 223 evidence events stored+
      ledgered (208 congress, 15 news, 13F politely unconfigured), 0 pitches (no candidate
      in zone — honest), **18 evidence alerts REALLY delivered via Telegram** (message_ids
      recorded); receiver started under the same flock the cron line uses
- [x] Gate green → commit

### Task 8 — Docs, outcome, verification
- [ ] Close out pitch-v2 plan Task 5 (gate re-run done in Task 0; README line for KGV/analyst
      pitch; AUTOPILOT_LOG entry)
- [ ] README: evidence sources + delays + §105(c) note + automation section; PLAN.md new phase
      section checked off; outcome section in THIS plan doc
- [ ] verification-before-completion sweep + docs/sessions entry

## Needs Nico
- `EDGAR_USER_AGENT="name (email)"` line in `.env` for the 13F collector (one-liner; collector
  stays politely `unconfigured` until then).
- Repo remains local-only; before any publication: §105(c) STOCK Act note + Google News
  personal-use clause re-check (publish checklist).
