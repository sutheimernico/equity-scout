# Telegram Channel Split: Intraday Stream + Daily Digest Chat

**Date:** 2026-07-14
**Status:** Approved design (Nico, verbal spec + blanket go, same session as global universe)

> **REVISED same day (Nico):** one chat, daily-only. The existing chat receives exactly one
> delivery per day (18:00 chain: pitches WITH decision buttons + digest); the 15-min chain
> became inbox-only (`run_notify --inbox-only`). The channel-routing env vars stay available
> but are not needed for this setup. Sections below describe the original two-chat design.

## Goal (Nico's words, condensed)

Two Telegram chats:
1. **Intraday chat (short-term trading):** a scan every ~10–15 minutes during market hours
   that pushes findings to the phone as they happen — a running timeline.
2. **Daily chat (long-term):** one message per day summarizing the day and current
   opportunities — "congress member X bought Y", "stock Z looks interesting/undervalued".

## Current state

- One bot, one chat (`COPILOT_TG_BOT_TOKEN` + `COPILOT_TG_CHAT_ID`): decision pitches
  (buy/pass/later buttons), evidence alerts, receiver long-polls for button presses.
- Telegram entirely unconfigured on Nico's machine → everything lands in the dashboard
  inbox only (by design, fail-safe).
- Daily digest exists (`run_digest.py`) but is e-mail/stdout only — no Telegram path.
- Intraday chain runs every 30 min inside the US-market-window guard.

## Design

### Channel routing (one bot, three chat ids, all optional)

- `COPILOT_TG_CHAT_ID` (existing) — Nico's private chat = his user id. Stays the security
  gate for button presses (`extract_decision` checks the PRESSING USER's id, which works
  identically when the button lives in a group) and the fallback target for both streams.
- `COPILOT_TG_CHAT_ID_INTRADAY` (new, optional) — pitches + evidence alerts go here
  (groups/channels work; the bot must be a member). Falls back to the main chat id.
- `COPILOT_TG_CHAT_ID_DAILY` (new, optional) — the daily digest goes here. Same fallback.

With only the main chat configured, today's behavior is unchanged (everything in one
chat). Receiver outcome-edits must target the chat where pitches now live (intraday).

### Cadence: 30 → 15 minutes

Nico said "alle zehn Minuten oder so". yfinance prices are ~15 min delayed, so a 10-min
poll adds request load (today's rate-limit lesson) without adding information; 15 min is
the densest honest cadence. The market-window guard and all cooldowns stay.

### Daily digest content + Telegram delivery

`build_digest` gains two sections (pure rendering, both optional):
- **"Heute aufgefallen"** — today's evidence alerts (congress buys, 13F, insider
  clusters, voices) with ticker + reasons.
- **"Chancen im Blick"** — top watchlist candidates by entry composite, marking
  in-zone and value-gap ("unterbewertet") signals.

`run_digest.py` sends the digest to the daily chat when Telegram is configured
(chunked — Telegram caps messages at 4096 chars); SMTP/stdout behavior unchanged.

### Crontab installer becomes line-managing

The installer currently only appends missing lines — a cadence change would leave the
old `*/30` line running alongside the new one. It now REPLACES any existing line that
references a managed script filename, then appends the canonical line (idempotent,
preserves unmanaged lines like forward-paper).

## Out of scope

Second bot, per-chat content filtering beyond the two streams, digest scheduling change
(stays in the 18:00 chain), Telegram formatting/markdown.

## Needs Nico (one-time, ~5 min)

Create the two chats (e.g. two groups with the existing bot, or reuse private chat for
one stream), then set `COPILOT_TG_BOT_TOKEN`, `COPILOT_TG_CHAT_ID`,
`COPILOT_TG_CHAT_ID_INTRADAY`, `COPILOT_TG_CHAT_ID_DAILY` in `.env` and re-run
`./scripts/install_crontab.sh`.
