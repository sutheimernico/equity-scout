# Person Track Record v4 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Checkbox
> (`- [ ]`) syntax for tracking; one task per commit, gate green before each.

**Goal:** Every PERSON behind an evidence event (congress politicians now, tracked 13F
funds as their events accumulate) gets a MEASURED historical track record — n calls,
hit-rate vs SPY, mean abnormal return over 1M/3M horizons — shown on alerts/pitches,
and a single buyer with a strong, sufficiently-sampled record can alert alone.

**Go:** Nico, in-session 2026-07-10 ("Personen mit gutem Track-Record höher scoren —
Historie anschauen, schauen wie erfolgreich das gewesen wäre"; blanket go for the
session, worked autonomously).

## Source decisions (live-verified 2026-07-10)

| Source | Verdict | Notes |
|---|---|---|
| kadoa mirror `trades.json` | too shallow for backfill | capped at 5000 rows ≈ 2 months of filings |
| kadoa mirror `public/data/filer/<id>.json` | **use for backfill** | 435 per-person files, full purchase history with transaction/filing dates; fetch ONLY filers present in our evidence store (~50, not all 435) — polite + relevant. Mirror ships own `ret_30d`/`excess_since` fields: **ignored** — we measure with our own documented methodology or not at all |
| X/Twitter (Burry-style finfluencer calls) | stays OUT | free API discontinued 2026, Nitter mirrors fragile, ToS; re-verified via research agent 2026-07-10. The "famous investor" intent is served by 13F (Burry = Scion, already tracked). Manual-entry layer possible later if Nico wants it |
| 13F funds as persons | v1 from own store | quarter-diff events accumulate in `evidence_events` once `EDGAR_USER_AGENT` is set; scoring module is source-agnostic so funds ride the same path with zero extra code |

## Scoring methodology (research-backed: TipRanks method, Finfluencers/SSRN 2023, congress-trading literature)

- **Call** = one person's purchase of one ticker on one day. T0 = **filing_date**
  (the day the public could know — measures the edge a READER could have had);
  transaction_date kept for display.
- **Abnormal return** per call and horizon: `ticker_return(h) − SPY_return(h)`,
  h ∈ {21, 63} trading days. Both legs on the benchmark's aligned calendar
  (reuses `ml/entry_eval.relative_forward_return`).
- **Minimum-sample gate:** no score below **5 resolvable calls** — the UI says
  "zu wenig Daten", never a number (one lucky call must not top any ranking).
- **Recency weighting:** exponential decay over the call's age, half-life **540 days**
  (skill/access change: committee reassignment, strategy drift).
- **Person score** = recency-weighted mean abnormal return @63d; hit-rates and both
  horizons always shown next to it, never a bare opaque number.
- **Honesty caveats carried on every surface:** a disclosed trade is a TRADE, not a
  recommendation (tax/liquidity/diversification confound); disclosures lag (45d/135d);
  track record is history, never a forecast; ranking many persons over multiple
  horizons produces lucky "top performers" — n and both horizons are always displayed.

## Architecture

- `evidence/person_track.py` — pure: `Call` + `PersonScore` dataclasses,
  `calls_from_filer_payload(payload)` (kadoa filer JSON → purchase calls, honest skip
  counters), `calls_from_events(events)` (own store → calls, source-agnostic),
  `score_persons(calls_by_person, closes, *, now, horizons, min_calls, half_life_days)`
  (pandas panel in, dict[person, PersonScore] out; unresolvable calls counted, never guessed)
- `evidence/person_storage.py` — `person_scores` table, replace-per-(person, source)
  on refresh, `load_person_scores(db)` for API/aggregate
- `scripts/run_person_scores.py` — CLI: active congress filers from `evidence_events`
  → fetch their kadoa filer files (http seam, polite) → own 13F/congress events from
  the store → price panel via cached loader → score → persist; wired into
  `daily_copilot.sh` Monday branch (weekly refresh is plenty for 45d-lagged data)
- `evidence/aggregate.py` — congress line + alert reasons carry the track record when
  present: "Jane Doe (Track-Record: 12 Käufe, 58 % Treffer 3M, Ø +1.4 % vs SPY)";
  `select_evidence_alerts` gains rule 3: a SINGLE buyer alerts alone when their score
  passes `min_single_buyer_score` (default +2 % weighted abnormal @63d) AND n ≥ 5 —
  labelled "starker gemessener Track-Record (Historie, keine Prognose)"
- `api.py` `/api/evidence` — adds `person_scores` (sorted, gated entries flagged)

## Task backlog

- [ ] Task A — `person_track.py` pure scoring core + tests (fixture payloads, synthetic
      price panel, gate/decay/horizon edge cases)
- [ ] Task B — `person_storage.py` + tests (replace-on-refresh, load ordering)
- [ ] Task C — kadoa filer fetch seam + `run_person_scores.py` CLI + tests (fake http,
      fake panel; live smoke against real mirror + real yfinance)
- [ ] Task D — surfaces: aggregate.py track-record lines + single-strong-buyer alert rule,
      /api/evidence person_scores, daily_copilot.sh Monday wiring + tests
- [ ] Task E — docs (README evidence section grows person scoring; this plan's outcome)

## Needs Nico
- unchanged from v3 (EDGAR_USER_AGENT, crontab installer) — no new items.
