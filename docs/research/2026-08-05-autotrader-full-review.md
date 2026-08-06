# Autotrader Full-System Review — 2026-08-05

Status: review only, nothing changed. Author: Claude (deep review session, 4 sub-audits:
architecture/state, learning loops, signal layer, Alpaca capabilities). Complements
`docs/superpowers/specs/2026-08-05-vision-v15-two-depots-evidence-learning.md` (see its
review addendum).

## 1. Verdict

**Methodically on the right track, economically not yet.** The honesty infrastructure
(look-ahead-safe engine, cost floors, DSR/PBO, promotion gates, paper-only, predict-then-
resolve ledgers) is exactly what almost every retail algo project lacks — keep it, it is
the moat. But as of today there is **no measured edge anywhere in the system**, the
learning loop has **never produced a single resolved feedback data point**, and the only
model that trades has been frozen since 2026-07-05. "The system keeps learning" is
currently an aspiration, not a fact. Leverage on top of the current state would only
amplify losses.

## 2. Performance reality (queried 2026-08-05, read-only)

| Lane | Capital | Return | Benchmark | Trades | Source |
|---|---|---|---|---|---|
| Auto-Depot (long-term) | $100k | +0.65% | SPY +3.03% | 64 | autotrader.db (first valuation 2026-07-16) |
| swing (arena) | $10k | +0.15% | SPY +3.92% | 6 | shortterm.db |
| session (arena, ORB) | $10k | **−1.70%** | SPY +3.60% | 48 | shortterm.db |
| crypto (arena) | $10k | −0.86% | BTC −0.47% | 14 | shortterm.db |

~3 weeks of forward track — statistically meaningless as a verdict on the strategies, but
it establishes: there is no evidence-backed edge to leverage today. `promoted_lanes: []` —
no arena lane has ever cleared the gate (≥30 trades, ≥60 days, net>0, PF≥1.1;
`src/equity_scout/promotion.py:15-70`).

## 3. Core findings

### F1 — Resolve loop: root cause found (calendar-days vs trading-days)
`src/equity_scout/ml/prediction_ledger.py:63-67` computes `resolve_after` with
`timedelta(days=horizon_days)`, but `horizon_days` is a **trading-day** horizon consumed by
`entry_eval.py:36-39` (`forward_return` needs `horizon_days` price rows after the
prediction). 20 trading days ≈ 28 calendar days, so rows come "due" 1–4 weeks early; the
resolver then correctly refuses (incomplete window) and prints "OK / Aufgelöst: 0" —
indistinguishable from "nothing due". Empirically reproduced: 150 of 299 rows due, panel
has 18 trading rows since 2026-07-10, all 150 need 21 → 0 resolvable. The oldest batch
becomes genuinely resolvable ~2026-08-07/08 *if the daily chain keeps running*. The
docstring claim "deliberate over-estimate" is backwards.
**Fix:** advance `resolve_after` in trading days (reuse NYSE-session logic) or at minimum
`ceil(horizon_days * 7/5)` + holiday margin; correct the docstring; make the resolver log
"n due but window incomplete" distinctly from "0 due".
**Update (same evening):** `docs/superpowers/plans/2026-08-05-v15-wave1-resolve-honesty.md`
now exists (written by the v15 planning strand) and covers this fix plus two further bugs
this review had not caught: the resolver's common-range panel trim (one young global ticker
truncates all histories) and silently shifted measurement windows. That plan supersedes
this finding's fix sketch.

### F2 — Silent scheduler gap (operational P0)
The daily chain did not fire 2026-07-23 → 2026-08-04 (11 days; visible in `copilot.log`
and the valuation gap in `autotrader.db`). Every daily loop (resolve, lanes, valuations,
evidence) starved silently — logs look identical to "nothing was due". No heartbeat or
staleness alarm exists. The Windows daily task is still NOT registered
(`docs/scheduling.md:148`, Needs Nico), so the chain depends on WSL being up at the right
moment.
**Fix:** staleness watchdog (e.g. daily chain checks `daily_last_run` age at start of the
nightly chain and vice versa; Telegram alert when > 48h stale) + register the Windows task.

### F3 — Model families: one frozen champion, two coin-flip families
From `entry_models` (85 rows) + `champion_history` (0 rows):
- `entry`: champion v1 since 2026-07-05 (AUC 0.6195 on only n_oos=220). 76 challengers
  since; best OOS AUC ≈0.518 on n_oos≈3550 — none cleared MIN_AUC_DELTA. All 299 live
  predictions were scored by model_version=1.
- `entry_short`: 28 versions, best AUC 0.5048, never a champion.
- `entry_tb`: 28 versions, median AUC ≈0.4706 (below random), never a champion.
- 16 versions per family (07-15 → 07-23) trained with n_oos=0/auc=None — a week of nightly
  compute produced nothing gradeable, silently.
- Large IS→OOS gaps everywhere (is_auc 0.55–0.89 vs oos ~0.51): the features carry almost
  no signal; more nightly retrains of the same features will not change that.
**Conclusion:** retire/rotate coin-flip families (v15 P3 is right); redirect compute toward
*new information* (evidence features, rank-IC-validated factors), not more retraining.

### F4 — Evidence layer is annotation-only, with one exception
All collectors (news themes, Form 4, Congress, 13F, 8-K, voices) are implemented, honestly
labelled, and never touch a trading decision (verified by grep across
radar/signals/engine/autotrader_engine/lanes/st_session/pipeline/entry). **Exception:** the
event classifier's bullish earnings events (beat/guidance_up) already trade via the arena
`swing` lane (`st_swing.py`) — the v15 spec relies on this ("news events need no new
lane"). Everything else, including Form 4 and Congress, is display-only; the screener's
factor ranks are the only other selection input that trades. v15 P2 ("evidence that
trades", gated insider/congress lanes) remains the single largest vision gap.

### F5 — News latency: RSS floor stands, but Alpaca/Benzinga is an untested free upgrade
The documented free-data floor (30–45+ min event→signal via RSS + 15-min polling,
vision-v7 plan) still holds for the current collectors. New finding: **Alpaca's News API
(Benzinga) is included in the free plan** (REST + websocket, 200 calls/min free tier).
Publish-to-delivery latency is undocumented anywhere — it must be measured empirically
before any design bets. If it lands in the seconds-to-few-minutes range, a news-event lane
becomes honestly buildable at minute latency; still nowhere near "milliseconds".

### F6 — Leverage/shorts/options: mechanically available on paper, strategically not earned
Alpaca paper (free): shorting simulated (ETB/HTB flags; borrow fees NOT simulated —
optimistic), Reg-T 2x margin (PDT rule retired June 2026, replaced by Alpaca's intraday
margin framework), **Level 3 options by default on paper** (long calls/puts, spreads,
multi-leg) — but free options data is an *indicative* feed only; real OPRA costs $99/mo.
Leveraged ETFs (TQQQ/SOXL/…) trade like normal equities — the simplest honest "leverage"
without margin mechanics. Paper fill realism is an optimistic upper bound by Alpaca's own
docs (no liquidity check, crude 10% random partial fills, no borrow fees/market impact).
**Policy recommendation (proposed, needs Nico's decision):** leverage of any form only for
a lane that has cleared its promotion gate *unleveraged*; leverage multiplies edge, and
today every measured edge is ≤ 0 (session lane −1.7% unleveraged → 5x would be ≈ −8.5%).

### F7 — Session lane / Alpaca wiring is NOT live yet
`scripts/run_shortterm.py` has zero references to the new Alpaca modules; Tasks 6/7/9 of
`docs/superpowers/plans/2026-08-04-session-lane-alpaca-paper.md` are unchecked; the
freshness precondition has never passed (no `.state/alpaca_verified`); no real order has
ever reached Alpaca. Owned by the parallel session — do not touch from other strands.

### F8 — Stale bookkeeping (small, erodes trust in "Needs Nico")
PLAN.md's "Handy-Cockpit scharf schalten" bullet is done in reality (DASH_TOKEN set,
dash service active on :8420) but still listed as open; PLAN.md:360 session-lane backlog
line is superseded by the 2026-08-04 plan. `evidence_predictions` (1187 rows, 0 resolved)
is NOT broken — genuinely not due before 2026-09-08.

## 4. Vision reality check (the honest sparring section)

- **"Millisecond news reaction"**: not achievable in this setup, with any budget class we
  operate in. HFT firms react in microseconds; the first seconds after news have exploding
  spreads and adverse selection — being 11th fastest pays worse than being deliberately
  slow. The honest play: minute-latency event detection (measure Benzinga), strategies
  that do NOT depend on being first (post-event drift, overnight reaction, earnings
  follow-through), and the slow disclosure signals (insider clusters have academically
  documented drift over weeks — 45-day-lagged Congress data is a swing signal, correctly
  scoped in v15).
- **"Leveraged day trader printing money"**: leverage is a multiplier on edge, not a source
  of it. Sequence must be: find edge unleveraged → survive the gate → then size up.
  Anything else is amplified noise.
- **"Continuously learning"**: currently false in both directions — the feedback loop never
  closed (F1/F2) and the trainable families have no signal to learn (F3). Fixing the loop
  is necessary but not sufficient; new information sources (F4/F5) are where improvement
  can actually come from.
- **Realistic ceiling**: a good honest systematic retail setup that survives its own gates
  is a single-digit-to-low-teens % p.a. machine with drawdowns, compounding over years —
  not a get-rich-quick device. Paper results additionally overstate live results (F6).
  Worth building anyway: the infrastructure, the honesty discipline and the measured
  track record are the portfolio-grade asset.

## 5. Recommended roadmap (amendments to v15, not a replacement)

Priority order:
1. **P0a Resolve fix** (F1) — small diff, unblocks every downstream learning metric.
2. **P0b Scheduler watchdog + Windows task** (F2) — without it, every loop silently starves
   again; alerting via existing Telegram seam.
3. **P1 Long-term depot routing** (v15, unchanged) — after the session-lane plan closes.
4. **P2 Evidence that trades** (v15, unchanged: insider-cluster / congress / news-event
   lanes behind the standard gate) — this is where new edge can plausibly come from.
5. **P2b Benzinga latency probe** (F5, new) — a tiny measurement script logging
   event-publish vs delivery timestamps for a week; decides whether the news-event lane
   runs on Benzinga (minutes) or stays on RSS (30–45+ min, drift strategies only).
6. **P3 Learning that learns** (v15, sharpened by F3): family retirement rules,
   champion_history backfill, rank-IC on run_scores (ADR 0003 — a month of history now
   exists), v14 champion→sleeve promotion with fresh forward track.
7. **v16 candidate — leverage policy** (F6, needs Nico's explicit decision): gated
   introduction of shorts/leveraged ETFs in the day-trader depot only for lanes that
   cleared their gate unleveraged; options deferred until a real OPRA feed exists (paid)
   or an indicative-feed-honesty story is written; borrow-fee/fill-realism haircuts
   documented on every leveraged surface.
8. **Catalyst position lane + long-horizon event study** (added 2026-08-06 after Nico's
   Trump/Intel direction; details in the v15 spec's "Second pass" section): the arena
   holds nothing between 5 days (swing) and the Auto-Depot's ETF book — the measured
   INTC case (5.1x in 12 months from a next-day-open entry, −42% drawdown en route)
   lives exactly in that hole. Proposed: `catalyst` lane (weeks–months holds),
   `government_intervention`/`endorsement` event class, event_reactions horizons
   1m/3m/6m. Measure the base rate over ALL such events before capital follows.

## 6. Needs Nico (consolidated from this review)

- Go/no-go on the v15 plan (spec awaiting approval) including the amendments above.
- Decision on the leverage policy (F6) — gate-first, as recommended, or not at all.
- Register the Windows daily task (`./scripts/install_windows_task.sh`) — closes F2's
  biggest operational hole.
- Reset of the old Alpaca account `PA3AKCY23RCD` (v15 P1 precondition, unchanged).
- PLAN.md hygiene: tick the done "Handy-Cockpit" bullet, supersede the stale session-lane
  backlog line (can be done by the loop once v15 planning starts).
