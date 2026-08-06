# Vision v15 — Two Depots, Evidence that Trades, Learning that Learns (Spec)

Date: 2026-08-05 · Author: Claude (session with Nico) · Status: awaiting plan approval

## Direction (Nico, 2026-08-05)

Two paper depots as the user-facing product — a **long-term trader** and a **day trader** —
each backed by its own strategy system and each routed to its own real **Alpaca PAPER**
account. Behind them: signal systems that ingest news, insider purchases (SEC Form 4) and
politician trades (Congress disclosures) and that **demonstrably keep learning**. Goal
framing: maximize risk-adjusted paper returns with honest measurement. Real-money trading
stays categorically forbidden (LOOP.md hard line, unchanged by this vision).

## Decisions locked in chat (2026-08-05)

1. **Long-term depot account:** the OLD Alpaca paper account `PA3AKCY23RCD` is repurposed
   from signal-trader-demo. Its existing broker book (1× AAPL) is sacrificed; Nico resets
   the account in the Alpaca dashboard (**Needs Nico** before routing goes live).
   signal-trader-demo keeps its keys but must be noted as "broker book retired".
2. **Day-trader depot account:** the dedicated "Short Term" account `PA3SIKMAPF0N`, already
   being wired to the session lane by the 2026-08-04 session-lane plan (separate work
   strand — NOT part of v15).
3. **Signal placement:** Congress/insider purchases are swing/long-term signals (up to
   45-day filing delay) — they must NOT be sold as day-trading signals. News events serve
   the short-horizon side.

## Current-state findings that motivate the scope (2026-08-05 analysis)

- All evidence sources (news themes, Form 4, Congress, 13F, voices) are already ingested
  but are annotation-only by design — they never trade.
- The predict-then-resolve loop is mis-calibrated, not dead (root-caused 2026-08-05, Opus
  diagnosis): `resolve_after` is stamped in CALENDAR days while resolution measures TRADING
  days, so all 299 `entry_predictions` since 2026-07-10 became "due but physically
  unmeasurable" ~8 days early and the resolver mutely printed "Aufgelöst: 0" for 26 days.
  Worse, two armed landmines would have made the FIRST real resolutions (due 2026-08-10)
  silently wrong: the resolver is the only sibling using `load_etf_panel`/`clean_panel`
  (common-range trim kills history for global tickers like 5101.T/CQR.AX), and a panel that
  starts after `created_at` silently measures a shifted window instead of returning None.
  The learning curve is empty (6 snapshots, all n_resolved=0) partly for this reason,
  partly because the nightly chain only runs when the box is awake. **P0 deadline: land
  before the 2026-08-10 nightly run**, or the first resolved numbers are corrupted.
- entry_tb/entry_short have never produced a champion (28 nightly runs, best AUC ≤ 0.51);
  the single `entry` champion has been unbeaten since 2026-07-05.
- The only learning loop that actually changes live behavior is the arena→depot promotion.
- The v14 strategy-parameter search found champions but deliberately never promotes them
  (v15 candidate left open in PLAN.md:440).

## Scope

- **P0 — Repair the resolve loop** (Wave 1 plan, deadline 2026-08-10). Trading-day
  due-gate, column-wise panel loader, shifted-window guard, observable no-op counters,
  one-off re-stamp of the open rows. Learning-snapshot gaps are an availability problem
  (box asleep at 02:30) — fixed by registering the Windows nightly task (Needs Nico),
  not by code.
- **P1 — Long-term depot routing.** Route the Auto-Depot's next-open orders to the
  repurposed Alpaca paper account, with broker-is-truth reconciliation for the routed
  subset. Non-US/non-tradable positions stay book-only and are visibly labelled — the
  internal book remains the complete truth; the broker account mirrors the tradable part.
- **P2 — Evidence that trades.** New, separately measured arena lanes fed by existing
  evidence collectors (insider-cluster lane, congress-purchase lane, news-event lane for
  the short-horizon side). Each lane starts as paper track only and must earn depot
  promotion through the existing gate (≥30 trades, ≥60 days, net>0, PF≥1.1). Evidence
  stays annotation-only everywhere else; no change to screener selection rules.
- **P3 — Learning that learns.** Champion→sleeve promotion for the strategy-parameter
  search (new sleeve identity with fresh forward track, analogous to the arena gate);
  rank-IC tracking on run_scores history (ADR 0003 direction); retirement/rotation rules
  for permanently coin-flip model families so nightly compute goes where evidence is;
  promote the manual self-checks (drift scan, PBO) to scheduled steps.

## Out of scope (backlog, not this vision)

- P4 additional intraday strategies (gated on the session lane's Alpaca freshness check
  going green and its post-change track building up).
- Overnight/hours-to-days lane (deliberately deferred 2026-08-05, see latency plan).
- Real-money anything. Paid data anything.

## Hard constraints (inherited, restated)

- Free data only (yfinance / EDGAR / public lists / keyless feeds / Alpaca paper+IEX).
- Paper only; the LOOP.md live-trading line is never widened by this work.
- Every new lane/sleeve gets its own honest track with its own DSR/multiple-testing
  context; no silent identity changes to existing tracks (`execution_regime`-style breaks
  where conventions change).
- Evidence annotates the funnel; it may TRADE only inside its own gated lanes.
- LLM interprets, never predicts or ranks prices.
- Determinism in tests; broker/network I/O behind seams, faked in tests.

## Plan documents (one per wave — each produces working software on its own)

1. `plans/2026-08-05-v15-wave1-resolve-honesty.md` — P0. Written 2026-08-05, ready.
2. P1 long-term depot routing — to be written AFTER the session-lane plan closes (it is
   actively editing `alpaca_broker.py` call sites / `scripts/run_shortterm.py`; exact
   diffs against a moving file would be stale on arrival) and after Nico resets the
   repurposed account. Architecture locked here: parameterised `auth_headers` env names
   (`ALPACA_LT_API_KEY_ID`/`ALPACA_LT_SECRET_KEY`), new market-on-open order path
   (`time_in_force="opg"`, whole shares via the existing `int(qty)` convention), a new
   `autotrader_broker.py` that converts the account blob's `pending_orders` targets into
   OPG deltas vs broker positions (routable subset = no "." suffix, no `ARENA_*`
   synthetics), an `lt_orders` table for expected-vs-actual slippage, a new
   `step autotrader_broker` after `step autotrader` in `nightly_train.sh`, and
   `session_reconcile.reconcile()` reused for the routed subset. The internal book stays
   the complete truth; the broker mirrors the tradable part.
3. P2 evidence lanes — to be written after the session-lane plan closes (shares
   `scripts/run_shortterm.py`). Architecture locked here: two NEW lanes `insider`
   (Form-4 cluster entries, ≥3 distinct insiders per `evidence/aggregate.py` convention)
   and `congress` (purchase filings ≤3 days old; longer exits than swing — filing delay
   makes this a swing/position lane, NOT day trading). News events need NO new lane —
   the existing `swing` lane already trades classified news events. Registration points:
   `shortterm_storage.LANES`/`LANE_LABELS`, new `st_insider.py`/`st_congress.py`,
   `run_shortterm.py` runners, cron lines, `KurzfristArenaPanel.tsx` label maps. Both
   lanes start at 10k paper and must earn depot promotion via the existing gate.
4. P3 learning mechanics — no file overlap with the session-lane strand, plannable next.
   Scope: champion→sleeve promotion for the strategy-parameter search (distinct sleeve
   `.name` carrying params, fresh `ForwardAccount` forward track first, depot inclusion
   only after a proof gate analogous to `promotion.py`), rank-IC tracking on `run_scores`
   history (ADR 0003 direction, computed from cached quotes with honest coverage label),
   and cadence rotation for permanently coin-flip model families (entry_short/entry_tb
   → weekly instead of nightly after N champion-less nights, state in `app_state`).

## Sequencing / coordination

The 2026-08-04 session-lane plan (Tasks 6+9) is being executed by a parallel autopilot
session and owns `st_session.py`, `alpaca_*.py` call sites and the intraday cadence.
v15 execution must not start P1 (which extends `alpaca_broker.py`) until that plan's
outcome section is closed, to avoid working-tree collisions. P0 has no file overlap with
that strand and may start immediately.

## Review addendum (2026-08-05, full-system review)

A same-day deep review (`docs/research/2026-08-05-autotrader-full-review.md`) confirmed
this spec's scope and adds the following deltas for the plan:

- **P0**: the review independently root-caused the calendar-vs-trading-day stamp and
  confirms the wave-1 plan's diagnosis (0 of 150 due rows physically resolvable today;
  the loop is *late*, not permanently dead). The wave-1 plan additionally covers the
  panel-trim and shifted-window bugs the review had not caught — no scope delta.
- **P0 gains a sibling**: a scheduler staleness watchdog (daily chain silently gapped
  2026-07-23 → 2026-08-04 for 11 days; Telegram alert when a chain is > 48h stale) plus
  the still-unregistered Windows daily task (Needs Nico).
- **P2 gains a precursor**: a Benzinga (Alpaca News API, free tier) latency probe —
  measure publish→delivery latency for ~a week; it decides whether the news-event lane
  can run at minute latency instead of the 30–45+ min RSS floor.
- **P3 sharpened**: entry_short/entry_tb have never left the no-edge band in 28 nightly
  versions each and all 299 live predictions were scored by the frozen 2026-07-05
  champion — family retirement/rotation is not optional polish, it is where the nightly
  compute stops being wasted.
- **New v16 candidate (Nico decision)**: gated leverage policy for the day-trader depot —
  shorts/leveraged ETFs only for lanes that cleared their promotion gate unleveraged;
  options deferred (free feed is indicative-only). Alpaca paper supports all of it
  mechanically (Level 3 options by default; PDT retired June 2026), but paper fills are
  an optimistic upper bound by Alpaca's own docs.

## Second pass (2026-08-06, Nico direction: "catch the Trump/Intel-type event, leveraged")

Measured case study (yfinance, INTC): entry at the NEXT OPEN after the 2025-08-07/08
Trump headlines = $19.95 → $101.06 on 2026-08-05 = **5.1x in 12 months**, with a **−42%
drawdown** (June–July 2026, $140.94 → $81.88) on the way. Two structural lessons for v15:

1. **Latency was irrelevant for this class of event.** Next-day-open capture kept
   essentially the whole move; the return came from *holding for months through a −42%
   correction*, not from reacting in milliseconds. The arena's horizon grid has a hole
   exactly there: session (intraday), swing (1–5 days) — nothing holds weeks-to-months.
   **Proposed P2 amendment (needs Nico's go): a `catalyst` position lane** — event-driven
   entries (government intervention/endorsement, transformative-stake class), holding
   period weeks–months with wide trailing exits, 10k paper, standard promotion gate.
2. **Measure before believing: extend the event study, not the conviction.** Proposed P2
   amendments: add a `government_intervention`/`endorsement` class to
   `event_classifier.py`, and extend `event_reactions.py` horizons beyond 1d/5d to
   1m/3m/6m for catalyst classes — so the base rate over ALL such events (including the
   DJT-style losers) is measured before any capital follows. Survivorship warning applies:
   Intel is the remembered winner, not the expected value.
3. **Leverage math, honest:** a 5.1x unlevered move becomes ~8-9x on 2x Reg-T margin
   (if held through the drawdown, financing costs off), or ~15-25x on the premium of a
   long-dated ATM call (defined risk, total loss if the thesis fails). "10,000-20,000x
   on one trade" does not exist in any instrument this project can touch. For catalyst
   rides, defined-risk long options are structurally safer than margin (a −42% correction
   margin-calls levered stock but only marks down an option) — sharpens the v16 leverage
   candidate: **defined-risk instruments preferred over margin for the catalyst lane**,
   still gate-first, still paper-only.

## Proposed P2a — Historical catalyst backfill ("initial anlernen", Nico direction 2026-08-06)

Goal: give the catalyst/insider/congress lanes 10–20 years of measured priors instead of
starting blind. Web-verified free sources (2026-08-06 research session):

- **Congress trades 2012→present**: kadoa-org/congress-trading-monitor static JSON
  (~54–57k transactions, ~380–430 filers; the collector the repo already uses — full
  history sits in its `public/data/`). Known gap: Senate pre-2015 is paper-only. The old
  Senate/House Stock Watcher sites are dead (domains expired) — do not plan on them.
- **Form 4 insiders 2006→present**: SEC official "Insider Transactions Data Sets" —
  quarterly TSV ZIPs (2006 Q1–2026 Q2, ~150–200k filings/yr). Compliant UA required.
- **Presidential/person statements**: Trump Twitter Archive 2009–01/2021 (bulk CSV
  mirrors: Kaggle/Internet Archive/GitHub); Truth Social 2022→ via community mirrors
  (github.com/stiles/trump-truth-social-archive auto-updating CSV, CNN JSON endpoint) —
  best-effort, deletion gaps labelled. Ticker mapping via the existing deterministic
  voices-style resolver; the LLM never scores anything.
- **13F 2013 Q2→present**: SEC official quarterly data sets (extends person_track depth).
- **Headline existence check 2015→**: GDELT GKG (metadata only). CAVEAT: the practical
  access path is BigQuery, which requires a Google Cloud account — that collides with the
  private-projects hard line "nothing cloud". Either **Needs Nico** (explicitly allow a
  free-tier BigQuery account) or drop GDELT — it is a nice-to-have cross-check, not a
  load-bearing source; raw flat-file downloads are TB-scale and not a serious alternative.

Design (reuses the event-study DNA): `historical_events` table with PIT T0 = filing/post
timestamp → forward returns vs SPY at 1w/1m/3m/6m/12m → base rates per class and person →
conditional splits ONLY on deterministic features (cluster size, buyer role/committee,
transaction size, market cap, sector, prior 6m momentum, regime), time-split validation
(fit ≤2021, validate 2022→), minimum-N per cell, multiple-testing hurdle as everywhere.
Findings seed the P2 lanes' entry filters as PRIORS; promotion still requires the forward
paper gate — history informs, the forward track proves.

**Hard honesty limit (stated up front): survivorship bias.** No free source covers
delisted US equities (verified — Stooq undocumented, real coverage is paid-only:
Norgate/Finaeon/EODHD). Events whose ticker later delisted cannot be resolved with
yfinance; they are counted and reported as a coverage gap on every study surface, never
silently dropped — measured hit rates are an upper bound. Expected-N reality check:
insider clusters (thousands of events) and congress purchases (tens of thousands of rows)
support real conditional analysis; presidential endorsements are likely a few hundred
events at most — enough for base rates and coarse splits, not for pattern mining.

## Completeness check against the full vision (2026-08-06)

Vision-element coverage as of this revision:

| Vision element | Where in v15 | Status |
|---|---|---|
| Two depots on real Alpaca paper accounts | P1 + session-lane strand | covered |
| Politician/insider signals that trade | P2 insider + congress lanes | covered |
| News that trades (short horizon) | swing lane (already live) + Benzinga probe | covered; true intraday news lane deferred until the probe measures latency |
| Trump/Intel catalyst rides (weeks–months) | catalyst lane + event classes + 1m/3m/6m horizons | covered (proposed) |
| Learn from 10–15y of history | P2a backfill | covered (proposed) |
| Continuous, demonstrable learning | P0 + P3 + watchdog | covered, plus P3 amendment below |
| Price/volume spike detection ("Ausschläge") | — | **was missing → added below** |
| Leverage / options / milliseconds | v16 candidate / excluded | deliberately NOT in v15 (gate-first; ms physically dishonest) |

Two additions closing real gaps:

- **P2 amendment — spike scanner (new evidence collector):** a deterministic
  unusual-move detector over the cached universe — relative volume (e.g. ≥3x 20-day
  median) combined with a price move ≥2 ATR, computed from data already fetched daily;
  intraday variant for the 12-ticker session universe from existing IEX bars. Starts
  annotation-only (evidence_events class `spike`, alerts labelled like all evidence),
  enters the predict-then-resolve ledger from day one so its base rate is measured before
  any lane may consume it. No new data source, no new cost.
- **P3 amendment — evidence features into the entry models:** the entry family's
  challengers have been feature-starved (OOS AUC ~0.51 vs IS 0.55–0.89 across 76
  versions). Add deterministic evidence-derived features to the entry-model feature set —
  active insider-cluster flag, recent congress-purchase count, classified-event
  recency/class, spike flag, person-track score of involved buyers — sourced from tables
  that already exist (plus P2a history for training depth). The existing champion gate
  (MIN_AUC_DELTA, per-family multiple-testing) remains the sole promotion path, so the
  new features must *prove* they beat the frozen 2026-07-05 champion. This is the
  mechanism that makes "the system keeps getting better" possible rather than aspirational.

With these, the spec covers every vision element that is honestly achievable on the
free/paper stack; leverage (v16), options (v16+), broader intraday strategies (P4) and
sub-minute news reaction (excluded as dishonest) are sequenced behind gates, not missing.
