# Plan: Vision v12 — "One Autotrader" (hardening · horizon integration · mobile cockpit · proof)

> **For agentic workers:** execute task-by-task (inline loop or subagent per task). Steps use
> checkbox (`- [ ]`) syntax for tracking. Gate per task: `uv run pytest -q` +
> `uv run ruff check .` (FE tasks also `npm --prefix frontend run typecheck` + `npm --prefix
> frontend run build`). Conventional Commits, English, imperative.

**Spec:** `docs/superpowers/specs/2026-07-20-vision-v12-one-autotrader.md` · **Branch:** `autopilot/work`

**Goal:** Fix every P0/P1 from the 2026-07-20 three-track adversarial review, unify
short/mid/long into one measured system with an evidence-gated promotion path, make the
dashboard a phone-installable LAN cockpit behind a token, and ship the proof surfaces
(metrics, monthly report, dead-man watchdog) that let Nico judge whether the system can work.

**Review grounding (2026-07-20, three parallel reviewers):** core = arithmetic/fills/netting
clean, but depot runs WITHOUT position exits (docstring claim false) and persist is non-atomic;
arena = settled-bar honesty solid, but stale positions meet today's opening range (P0),
persistence non-atomic, silent-stall paths unalarmed; notify/API = intraday path robust, but the
18:00 digest dies permanently on one network blip and nothing may go LAN without auth.

## Wave R — hardening (order matters: R1 first, R2 before R3/R4)

- [x] **R1 (P0) session lane: force-flat stale positions** — `src/equity_scout/st_session.py`:
  new guard at the top of the lane step (before `decide()`): any held position whose
  `opened_at` date != today's `session_date` is closed immediately at the first settled bar's
  open with `reason="stale_flat"` (books through `shortterm_book` like the overnight sweep).
  Wire in `scripts/run_shortterm.py:144-198` so the guard runs even when no OR exists yet.
  Tests (`tests/test_run_shortterm.py`): stale position + today's bars → flat fill booked,
  stop/target never computed from today's range; fresh same-day position → untouched.
- [x] **R2 (P1) central SQLite conventions** — new `src/equity_scout/db.py`: `connect(path)` →
  `sqlite3.Connection` with `timeout=30`, `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=30000`,
  row_factory unchanged. Adopt in `autotrader_storage.py` and `shortterm_storage.py` (all
  `sqlite3.connect` call sites). Tests (`tests/test_db.py`): WAL mode active, busy_timeout set,
  two concurrent writers on tmp DB don't raise OperationalError (writer B waits).
- [x] **R3 (P1) atomic autotrader persist** — `autotrader_storage.py`: new
  `persist_advance(db_path, account, valuation, trades, events)` doing ALL writes in ONE
  connection/transaction, valuation/trades/events first, account blob (`last_as_of`) LAST;
  `scripts/run_autotrader.py:141-144` switches from `save_depot`+`record_advance` to it.
  Tests (`tests/test_autotrader_storage.py`): crash injected between trade insert and account
  save (exception mid-transaction) → NOTHING persisted, guard does not block retry; success
  path round-trips; double-call same day stays idempotent.
- [x] **R4 (P1) atomic shortterm persist** — `shortterm_storage.py:91,108,132,168`: same
  pattern — `persist_lane_step(db_path, book, trades, valuation, state)` in one transaction;
  callers in `scripts/run_shortterm.py` switch. Tests: mid-persist exception → no partial rows
  (book unchanged, no orphan trades, marker not advanced).
- [x] **R5 (P1) depot position exits via sleeve books** — the honest fix for "depot has no
  exit discipline" WITHOUT duplicating exit machinery: the ML sleeves' forward_paper accounts
  already apply `ExitRules` nightly and run BEFORE the autotrader in `nightly_train.sh`. In
  `scripts/run_autotrader.py` sleeve-decision collection: for ML sleeves, tickers that the
  sleeve's own forward book does NOT currently hold (because exits closed them / blocked_today)
  get target weight 0 in that sleeve's contribution — i.e. the depot mirrors the sleeve's
  POST-exit book instead of raw `decide()`. Rule sleeves (allocation strategies, no per-name
  exits by design) stay raw. Correct the false docstring in `autotrader_engine.py:13-15` to
  describe this seam. Tests (`tests/test_run_autotrader.py`): fake ML sleeve whose decide()
  says long X+Y but whose forward book only holds X → aggregated target for Y is 0; docstring
  claim gone (grep-level assert not needed, code path tested).
- [x] **R6 (P1) digest delivery: persist + resend** — `scripts/run_digest.py:296-307`: on
  `TelegramError` store the rendered digest (`state_storage` keys `digest_pending_text`,
  `digest_pending_date`) and still exit 0 (guard semantics unchanged); new
  `maybe_resend_pending(...)` called at the START of every notify/digest chain entry
  (`run_digest.py` main and `scripts/run_notify.py` main): if a pending digest exists and
  `digest_sent_on` < its date → try send, on success `mark_sent` + clear pending. Tests
  (`tests/test_run_digest_guard.py`): TelegramError → pending stored, sent-marker absent;
  next run with working transport → resent exactly once, pending cleared; no pending → no-op.
- [x] **R7 (P1) digest freshness guards** — `digest.py` Auto-Depot block + Arena block: when
  the block's `as_of`/latest valuation `created_at` is older than 2 trading days (reuse an
  existing trading-day helper; weekend-aware), prepend "⚠️ Stand veraltet (N Tage) — Kette
  prüfen". Collector passes age. Tests (`tests/test_autotrader_digest.py`,
  `test_shortterm_digest.py`): fresh → no warning; stale → warning with day count.
- [x] **R8 (P1) intraday bars tz assertion** — `src/equity_scout/intraday_bars.py:34-56`:
  after fetch, assert bars index is tz-aware and convert to `America/New_York`
  (`tz_localize` raise if naive → raise `IntradayDataError` with clear message so the chain
  logs a loud, greppable failure). Tests: naive index → IntradayDataError; UTC-aware index →
  converted, settled logic unchanged.
- [x] **R9 (P2) allocator calendar gaps** — `autotrader_allocator.py:44-58`
  `sleeve_return_frame`: drop return observations whose date gap to the previous row exceeds
  4 calendar days (holiday-safe) instead of treating multi-day jumps as daily returns. Tests:
  synthetic series with a 10-day gap → that observation excluded from the Sharpe window.
- [x] **R10 (P2) market hours from NYSE calendar** — `market_hours.py:15-27`: compute the
  session window from `America/New_York` 09:30–16:00 converted to local time via zoneinfo
  instead of the fixed Berlin 15:00–22:30 slot. Tests: March DST-transition date → window
  starts 14:30 Berlin; normal summer date → 15:30 Berlin.
- [x] **R11 (P2) small robustness sweep** — (a) `api.py:462-498` `/api/entry/{ticker}`: wrap
  `fetch_entry_history` in try/except → `{"available": false, "reason": "fetch_failed"}`;
  (b) `scripts/run_receiver.py:73-87`: non-owner presser gets `answerCallbackQuery`
  ("nur für den Besitzer") instead of silent drop; (c) `st_swing.py:23-45`: skip events older
  than 3 trading days (no more buying week-old news after an outage) + document the
  limitation in the arena README section. Tests for each branch.

## Wave W — watchdog + telegram events

- [x] **W1 chain heartbeats + dead-man watchdog** — every guarded chain entry
  (`run_daily_guarded.sh`→`run_digest.py`, `nightly_train.sh` autotrader step, crypto lane
  step in `run_shortterm.py`) writes `state_storage` key `heartbeat_<chain>` = now on success
  (helper `record_heartbeat(name)` in `state_storage.py`). New `src/equity_scout/watchdog.py`:
  `overdue_chains(now)` returns chains whose heartbeat exceeds its SLA (daily: 26h, nightly:
  26h, crypto: 2h during any day, session: skipped — market-window dependent). Wire into the
  */15 intraday chain (`scripts/run_evidence.py --fast` path or a tiny `run_watchdog.py` step
  in `intraday_copilot.sh`): overdue → ONE Telegram warning per chain per 24h (cooldown via
  state key). Tests: overdue detection boundaries, cooldown suppresses repeat, fresh → silent.
- [x] **W2 auto-depot event push** — after a successful autotrader advance with ≥1 trade or
  ≥1 risk event, send ONE bundled Telegram message (trades table ≤ 10 rows + risk events) to
  the daily chat; env-gated `COPILOT_TG_AUTOTRADER_EVENTS=1` (default ON when chat configured),
  reuses `split_message`. Nightly runs ~02:35 — message lands silently (Telegram
  `disable_notification=true` so it doesn't wake Nico; the 18:00 digest stays the loud surface).
  Tests: message built from trades/events, env gate off → no send, notification silent flag set.

## Wave I — horizon integration

- [x] **I1 total-wealth API** — `api.py` `/api/overview`: one payload with per-book equity +
  day P&L + as_of (Auto-Depot, each arena lane, forward ML accounts optional) + combined total
  and per-horizon subtotals (short=arena, mid=ML sleeves, long=rule sleeves via autotrader
  sleeve weights). Read-only aggregation over existing storages. Tests: seeded tmp DBs →
  totals add up, missing books → honest omission with `available:false`.
- [x] **I2 promotion gate module** — new `src/equity_scout/promotion.py`:
  `lane_promotion_status(trades, valuations, cfg)` → dict(realized_trades, days_active,
  net_pnl_after_costs, profit_factor, eligible: bool, missing: [reasons]). Default cfg:
  ≥ 30 realized trades AND ≥ 60 calendar days active AND net P&L > 0 AND profit factor ≥ 1.1.
  Pure function, no I/O. Tests: each criterion individually failing → listed in `missing`;
  all pass → eligible.
- [x] **I3 promotion wiring (status-first)** — `scripts/run_autotrader.py`: at each advance,
  compute promotion status for all lanes from `shortterm.db`; an ELIGIBLE lane is added as a
  sleeve using its lane valuation series as the return source (same
  `sleeve_return_frame` contract), weight subject to the normal floor/cap; a promoted lane
  that later fails net-P&L>0 over its trailing 60d is demoted (state in autotrader account
  blob, `promotion_events` persisted as risk-event rows kind="promotion"/"demotion").
  IMPORTANT honesty: promotion only ever affects the PAPER depot; arena keeps its own book —
  the sleeve mirrors its equity curve, positions are NOT duplicated ticker-level (lane sleeve
  contributes weight to its own lane tickers via current lane holdings mapped to weights).
  Tests: eligible lane → sleeve appears with weights; ineligible → absent; demotion path.
- [x] **I4 integration surfaces** — digest: Arena block gains one line per lane
  "Prüfstand: 12/30 Trades · 41/60 Tage · PF 0.9" (from I2) and a 🎓 line on
  promotion/demotion events; FE: DepotsView "Kurzfrist-Arena" tab shows the promotion
  checklist per lane; new "Gesamt" tab (or top card) rendering `/api/overview` with horizon
  split. Gate incl. FE typecheck+build.

## Wave M — mobile cockpit

- [x] **M1 LAN bind + token auth** — `scripts/run_api.py`: `--host` flag (default
  `127.0.0.1`). `api.py`: middleware — if env `DASH_TOKEN` is set, every request must carry
  it (`?token=` once → sets `es_dash` cookie; or `X-Dash-Token` header; `hmac.compare_digest`)
  else 401 JSON; localhost requests exempt; if `DASH_TOKEN` unset AND host != loopback →
  server refuses to start (belt and braces: check in run_api.py before uvicorn.run). Static
  assets under the same gate (whole app is private). Tests: no token → 401, query token →
  cookie set + 200, header ok, localhost exempt, wrong token 401.
- [x] **M2 PWA shell** — `frontend/`: `public/manifest.webmanifest` (name "Equity Scout",
  display standalone, theme/background colors matching the dark token system, icons 192/512
  generated as simple monochrome PNGs into `public/icons/`), `index.html` link rel=manifest +
  `apple-touch-icon` + `theme-color` meta. No service worker in v1 (online-only cockpit is
  honest — the data is server-side anyway). Gate: build; manual: Lighthouse-installable not
  scriptable here → note in README.
- [x] **M3 dashboard server as a service** — `scripts/systemd/equity-scout-dash.service`
  (user unit: `uv run python scripts/run_api.py --host 0.0.0.0 --port 8420`, Restart=always,
  EnvironmentFile=.env) + `scripts/install_systemd_timer.sh` learns to install it (or a small
  `install_dash_service.sh` following the existing installer pattern); README ops section.
  Port 8420 (8000/8080/8123 taken by other projects). No test (ops artifact) — smoke = unit
  file lints via `systemd-analyze verify` if available.
- [x] **M4 phone onboarding** — digest gains a one-time-per-week footer line with the
  dashboard URL (`DASH_URL` env, e.g. `http://<lan-ip>:8420/?token=…`; rendered only when set);
  README "Handy-Cockpit" section: LAN setup, add-to-home-screen steps, token rotation, and the
  Tailscale option documented as **Needs Nico** (free tier, his sign-up). Tests: footer line
  gated on env + weekly state key.

## Wave P — proof

- [x] **P1 proof metrics module** — new `src/equity_scout/proof.py`:
  `book_report(valuations, trades, benchmark_series, label)` → dict(period, n_days,
  cagr_pct?, sharpe_annualised?, max_drawdown_pct, realized_win_rate?, cost_share_of_pnl,
  vs_benchmark_pct, verdict_label) where metrics needing more history return None + reason
  ("Track Record zu kurz (< 60 Tage)" style honesty labels — same pattern as MLBot.ready).
  Pure, tested against hand-computed fixtures (incl. drawdown and cost-share edge cases).
- [x] **P2 proof surfaces** — `api.py` `/api/proof` (report per book: autodepot, lanes,
  forward ML accounts; benchmarks: SPY for equity books, BTC for crypto lane); FE
  "Beweis" view: per-book cards with the honesty labels front and center + a plain-language
  German explainer ("Was würde mich überzeugen? ≥ 6 Monate, Sharpe > 1 nach Kosten, DD < 15%…"
  — thresholds rendered from code constants, not prose). Gate incl. FE.
- [x] **P3 monthly telegram report** — on the 1st of each month (state-gated
  `proof_report_month`, same pattern as butler core plan), daily chain sends a compact
  proof summary per book (from P1) + promotion statuses. Tests: fires once per month,
  renders None-metrics honestly, absent when no history.
- [x] **P4 docs closure** — README: "Kann das funktionieren?" section (what the system
  guarantees: discipline/costs/risk/measurement; what it cannot: alpha promise; what would
  justify real money and that this is a Nico-only decision with LOOP.md change); PLAN.md
  phase entry check-off; outcome section in this plan.

## Needs Nico (collected, do NOT block the loop)

- Set `DASH_TOKEN` + optionally `DASH_URL` in `.env`; decide whether the dash service binds
  `0.0.0.0` (LAN) — installer stages it, Nico flips it on.
- Optional: Tailscale account for out-of-home access (free tier, his sign-up).
- Optional later: paid data/serving upgrades (EODHD, VPS) — only after the proof surfaces
  convince him; documented, never signed up autonomously.

## Outcome (2026-07-21)

**All 25 tasks DONE** in one continuous loop session (2026-07-20 evening → 2026-07-21
early morning), single-threaded inline, gate green per commit (~1090 tests + ruff + FE
typecheck/build at the end).

- **Wave R (11):** P0 stale-session-flat, central WAL/busy-timeout, atomic persists
  (autotrader + shortterm), depot mirrors ML sleeves' post-exit books (false docstring
  corrected), digest persist+resend on TelegramError, staleness warnings, tz assertion,
  allocator gap filter, NYSE-based market window, robustness sweep.
- **Wave W (2):** chain heartbeats + dead-man watchdog in the 24/7 cron slot (live),
  bundled silent nightly trade/risk push (env-gated).
- **Wave I (4):** /api/overview (horizon subtotals), promotion gate module, promotion
  wiring (lane equity curve as ARENA_<lane> fund-share sleeve, demotion on trailing-60d
  net ≤ 0, events persisted), digest checklist + FE Gesamt tab.
- **Wave M (4):** DASH_TOKEN middleware (fail-closed LAN bind), PWA shell, staged
  systemd dash service (port 8420), weekly DASH_URL digest footer + README onboarding.
- **Wave P (4):** proof.book_report + CONVICTION_THRESHOLDS, /api/proof + FE Beweis
  view, monthly Telegram proof report (butler pattern), docs closure.

**Deviations:** none of substance; R5 chose the sleeve-book mirror over re-implementing
exits (design option named in the plan). **Live catch during verification:** the v11
crypto cron line ran without `cd` and wrote stray DBs into $HOME since install —
fixed (cron line now `cd`s), stray DBs quarantined to `data/stray-home-dbs-2026-07-21/`,
lane + watchdog live-verified against the repo DBs.

**Needs Nico:** DASH_TOKEN/DASH_URL + dash service enable (staged), Tailscale optional;
first nightly with promotion/exit-mirror runs 02:35 — check the 18:00 digest.
