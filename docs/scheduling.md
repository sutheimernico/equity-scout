# Scheduling equity-scout

Five layers of automation, all cron-driven and local/free (always-on since v6):

1. **`scripts/intraday_copilot.sh`** — every 15 minutes (densest honest cadence:
   yfinance prices are ~15 min delayed, so polling faster adds request load without
   adding information), ONLY inside the approximate US market window (15:00–22:30
   Europe/Berlin Mon–Fri, guard in `src/equity_scout/market_hours.py`): radar entry
   zones → fast evidence collectors (congress mirror, news themes, voices —
   `run_evidence.py --fast`) → notify `--inbox-only` (logs a line when a watchlist
   ticker has a known earnings date in the next few days — awareness only, it does
   not change pitch content or any decision). REVISED 2026-07-14: the intraday
   timeline accumulates in the dashboard inbox only — Nico gets exactly ONE Telegram
   delivery per day (18:00 chain: pitches with decision buttons + digest). Existing
   cooldowns + idempotency keys prevent alert spam. Appends to `intraday.log`.
2. **`scripts/daily_copilot.sh`** — the full unattended copilot chain at 18:00:
   (Mondays: screener first) → radar → earnings-calendar refresh (`run_earnings.py`,
   Strang B1: yfinance calendar for every watchlist/depot ticker) → ALL evidence
   collectors (incl. 13F + Form 4; EDGAR stays out of the 30-min loop by etiquette) →
   notify → score watchlist → resolve predictions → resolve evidence → lanes → digest
   (now with a "📅 Earnings diese Woche" section). Every step degrades independently
   and appends to `copilot.log`.
3. **`scripts/nightly_train.sh`** — 02:30 Tue–Sat (post-US-close): retrain every
   entry-model preset for both families (long + short; the registry gate alone
   promotes) → a daily learning-curve snapshot (`run_learning_snapshot.py`, Strang C
   task C1: the champion's `n_train` + rolling `n_resolved`/hit-rate/Rank-IC as one
   persisted point per calendar day, so `/api/model/history`'s `daily_curve` shows
   daily training even on nights the champion does not flip) → a 25-trial research
   batch, then advance the forward paper accounts so the ML bots trade the freshest
   champions. Appends to `train.log`.
4. **`scripts/receiver_keepalive.sh`** — restarts the Telegram decision receiver
   (under `flock -n`, single instance) so buy/pass/later buttons keep working after
   a reboot. Quiet no-op without Telegram config.
5. **`scripts/nightly_prefetch.sh`** — 00:45 Mon–Sat: warms one sixth of the ~7.5k
   universe through the read-through quote cache (2 workers, rate-limit backoff) and
   persists newly discovered sectors to `instrument_meta`. The Monday screener runs
   with `--cache-max-age 7`, so it ranks the whole universe from this warm cache and
   only live-fetches misses — instead of dying on yfinance rate limits (the
   2026-07-14 lesson: 5,275 of 6,318 names got gated as fetch victims). The rotation
   is stateless (day-of-year modulo): a missed night heals on the next pass.
   Appends to `prefetch.log`.

`scripts/scheduled_run.sh` remains the standalone screener run (also called by the
Monday branch of the chain).

## Crontab (install with `./scripts/install_crontab.sh`, idempotent)

```cron
# forward-paper strategies (pre-existing)
0 23 * * 1-5 cd /home/nicosutheimer/private/equity-scout && .venv/bin/python scripts/run_forward_paper.py --refresh >> /home/nicosutheimer/private/equity-scout/forward.log 2>&1
# daily copilot chain — 18:00 local, US market is open so radar zones use live prices
0 18 * * 1-5 /home/nicosutheimer/private/equity-scout/scripts/daily_copilot.sh >> /home/nicosutheimer/private/equity-scout/copilot.log 2>&1
# receiver keepalive — flock guarantees a single instance; no-op without Telegram env
*/5 * * * * flock -n /tmp/equity-scout-receiver.lock /home/nicosutheimer/private/equity-scout/scripts/receiver_keepalive.sh >> /home/nicosutheimer/private/equity-scout/receiver.log 2>&1
# intraday chain — cron fires blindly every 15 min; the market-window guard inside exits quietly
*/15 * * * 1-5 flock -n /tmp/equity-scout-intraday.lock /home/nicosutheimer/private/equity-scout/scripts/intraday_copilot.sh >> /home/nicosutheimer/private/equity-scout/intraday.log 2>&1
# nightly training — 02:30 Tue-Sat, after the US close and settled EOD data
30 2 * * 2-6 flock -n /tmp/equity-scout-nightly.lock /home/nicosutheimer/private/equity-scout/scripts/nightly_train.sh >> /home/nicosutheimer/private/equity-scout/train.log 2>&1
# nightly universe prefetch — 00:45 Mon-Sat, one universe segment per night (6-night rotation)
45 0 * * 1-6 flock -n /tmp/equity-scout-prefetch.lock /home/nicosutheimer/private/equity-scout/scripts/nightly_prefetch.sh >> /home/nicosutheimer/private/equity-scout/prefetch.log 2>&1
```

## Telegram delivery (2026-07-14, revised same day)

Nico's setup: ONE chat, ONE delivery per day. The 18:00 chain sends the day's pitches —
at least five (`--min-pitches 5`, topped up by composite), each a 1-year-chart photo with
a compact caption (Score, KGV, Kurs + €-Umrechnung, Zone, Analysten-Ziel, Evidenz,
Pressestimmen, Risiko) and buy/pass/later decision buttons (his manual lane vs. the ML
bots trading on their own) — followed by the digest (today's evidence: "Kongress hat X
gekauft", top opportunities, hit rates). The 15-min chain is inbox-only
(`run_notify --inbox-only`). Without any Telegram env everything stays in the dashboard
inbox.

- `COPILOT_TG_BOT_TOKEN` + `COPILOT_TG_CHAT_ID` — the bot and Nico's private chat
  (= his user id; also the security gate for buy/pass/later button presses).
- `COPILOT_TG_CHAT_ID_INTRADAY` / `COPILOT_TG_CHAT_ID_DAILY` — optional split targets
  (both fall back to the main chat). With the inbox-only intraday chain these only
  matter if the daily chain's pitches and digest should land in separate chats.

The installer REPLACES outdated managed lines (e.g. the old `*/30` intraday line), so
re-running `./scripts/install_crontab.sh` after an update never leaves two schedules
running in parallel.

**WSL caveat:** cron only fires while the WSL VM is running. If the laptop was off
at 18:00, that day's chain simply did not happen (the receiver comes back within
5 minutes of the next WSL start). Every consumer is idempotent, so a missed day
never corrupts state — the next run picks up where things stand.

## Option A — cron for the screener only (historic)

```cron
# Daily at 07:00 local time
0 7 * * * /path/to/equity-scout/scripts/scheduled_run.sh >> ~/equity-scout-cron.log 2>&1
```

Install with `crontab -e`.

## Option B — systemd user timer (survives reboots, better logging)

`~/.config/systemd/user/equity-scout.service`:
```ini
[Unit]
Description=equity-scout scheduled run

[Service]
Type=oneshot
ExecStart=/path/to/equity-scout/scripts/scheduled_run.sh
```

`~/.config/systemd/user/equity-scout.timer`:
```ini
[Unit]
Description=Run equity-scout daily

[Timer]
OnCalendar=*-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:
```bash
systemctl --user daemon-reload
systemctl --user enable --now equity-scout.timer
systemctl --user list-timers equity-scout.timer   # verify
```

## Notes
- `--use-llm` runs `claude -p` per finalist (capped to top-3/bucket). Drop `--use-llm` for a
  pure-quant run if you want zero LLM cost.
- yfinance over ~500 tickers takes a few minutes; the read-through cache makes repeat runs fast.
- This is a research snapshot, not a trade trigger. No orders are ever placed.
