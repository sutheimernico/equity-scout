# Vision v12 — "One Autotrader": review hardening, horizon integration, mobile cockpit, proof

**Date:** 2026-07-20 · **Status:** review complete, approved for autopilot build · **Direction (Nico, 2026-07-20):**
"Autotrader komplett reviewen und aufarbeiten; Vision = möglichst viel Kohle; short, midterm UND
long term in einem System; Telegram-Meldungen aufs Handy; Dashboard als Handy-App; Laptop läuft
rund um die Uhr als Server; ich muss erst überzeugt werden, dass das funktionieren kann."

## What this is

Four pillars on top of the finished v10 Auto-Depot + v11 Kurzfrist-Arena:

1. **R — Hardening:** every P0/P1 finding from the 2026-07-20 adversarial three-track review
   (core engine, arena+scheduling, notify+API+dashboard) gets fixed with a test. Findings are
   itemised in the plan doc once the review lands.
2. **I — Horizon integration:** short / mid / long become ONE measured system instead of two
   separate worlds. Explicit horizon framing (short = arena lanes, mid = ML bots, long = rule
   sleeves), a total-wealth view across Auto-Depot + Arena, and a **promotion gate**: an arena
   lane only graduates into an Auto-Depot sleeve after it has PROVEN itself on realised paper
   trades (net-of-costs positive over a minimum sample — thresholds in the plan). Until then the
   arena stays a measurement instrument. This is the honest version of "short term soll auch
   Geld machen": evidence first, capital second.
3. **M — Mobile cockpit:** the dashboard becomes reachable from Nico's phone with the laptop as
   the home-network server: opt-in LAN bind + shared-secret token auth (threat model: home LAN),
   PWA manifest + icons + responsive layout so "Add to Home Screen" yields an app-like cockpit.
   Access link surfaced where Nico already looks (Telegram digest). Remote access from outside
   the LAN (Tailscale) = Needs Nico, free tier, optional.
4. **P — Proof:** the "kann das funktionieren?"-evidence Nico asked for. A proof surface
   (dashboard + monthly Telegram report) with per-depot equity vs. benchmark, annualised
   Sharpe, max drawdown, realised win rate, cost share, and honest track-record-length labels;
   plus an operations dead-man switch (Telegram alert when a chain has not run) so the
   always-on server is trustworthy, not assumed.

Telegram event push (Auto-Depot trades, risk events, promotions, watchdog) is part of pillars
I/P — bundled, deduped, env-configurable. This deliberately revises the earlier "18:00 only"
decision per Nico's 2026-07-20 direction ("immer Telegram Meldung auf mein Handy"); the daily
digest stays the primary surface, events are additive and rate-limited.

## What this is NOT (iron constraints, unchanged)

- **No real-money trading, no order routing — ever** (LOOP.md). Broker facts stay a documented
  Nico-only decision. "Möglichst viel Kohle" is served by building the system that could be
  trusted with money, and the track record that would justify it — not by faking edge.
- Local & free only (yfinance/EDGAR/Kraken public/Telegram bot API). Paid data/serving =
  documented Needs-Nico options, never signed up autonomously.
- Every surface keeps the `DISCLAIMER`; expectation-after-costs statements stay on the arena.
- The LLM never forecasts or ranks prices.

## Success criteria

- All review P0/P1 findings fixed, each with a regression test; gate green (pytest + ruff + FE).
- One dashboard view answers "wie steht MEIN Gesamtsystem heute?" across all horizons.
- Lane→sleeve promotion is codified, tested, and fires only on evidence (or provably never fires
  on bad lanes).
- Dashboard installable as PWA from a phone on the LAN, behind a token; nothing newly exposed
  without auth.
- Proof view + monthly report render honest numbers from real stored history; dead-man watchdog
  alerts on silent chain failure.

## Where it lands

Plan + task breakdown: `docs/superpowers/plans/2026-07-20-vision-v12-one-autotrader.md`
(written after the review findings are in). Work runs on `autopilot/work` under the standard
gate (`uv run pytest -q` + `uv run ruff check .` + FE typecheck/build where touched).
