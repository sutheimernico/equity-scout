# Scheduling equity-scout

Five layers of automation, local/free and always-on since v6. Four are pure cron;
layer 2's daily chain gained two more non-cron triggers in v9 (see
**v9: Guaranteed Delivery** below):

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
2. **`scripts/daily_copilot.sh`** — the full unattended copilot chain, guarded to
   run once per weekday no matter which of three redundant triggers fires it
   (cron 18:00, systemd 18:05, Windows Task Scheduler 18:00 — v9, see below):
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
0 18 * * 1-5 /home/nicosutheimer/private/equity-scout/scripts/run_daily_guarded.sh cron >> /home/nicosutheimer/private/equity-scout/copilot.log 2>&1
# receiver keepalive — flock guarantees a single instance; no-op without Telegram env
*/5 * * * * flock -n /tmp/equity-scout-receiver.lock /home/nicosutheimer/private/equity-scout/scripts/receiver_keepalive.sh >> /home/nicosutheimer/private/equity-scout/receiver.log 2>&1
# intraday chain — cron fires blindly every 15 min; the market-window guard inside exits quietly
*/15 * * * 1-5 flock -n /tmp/equity-scout-intraday.lock /home/nicosutheimer/private/equity-scout/scripts/intraday_copilot.sh >> /home/nicosutheimer/private/equity-scout/intraday.log 2>&1
# nightly training — 02:30 Tue-Sat, after the US close and settled EOD data
# (v10.1: via run_nightly_guarded.sh — flock + per-day marker; trains, advances the
#  forward sleeves AND the Auto-Depot)
30 2 * * 2-6 flock -n /tmp/equity-scout-nightly.lock /home/nicosutheimer/private/equity-scout/scripts/nightly_train.sh >> /home/nicosutheimer/private/equity-scout/train.log 2>&1
# nightly universe prefetch — 00:45 Mon-Sat, one universe segment per night (6-night rotation)
# crypto lane — every 15 min around the clock (Kraken real-time is free and the market
#   never closes); idempotent per completed bar, flock against overlaps (v11)
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

**WSL caveat (mitigated by v9, below):** cron only fires while the WSL VM is
running, so a bare cron line has exactly one shot per day — if the laptop was off
at 18:00, that day's chain simply did not happen (the receiver comes back within
5 minutes of the next WSL start). Every consumer is idempotent, so a missed day
never corrupted state, but v6-era "missed" meant "skipped, catch up tomorrow."
See **v9: Guaranteed Delivery** for the redundant triggers and catch-up layer that
now cover this for the 18:00 daily chain specifically (the 15-min intraday chain,
nightly training and nightly prefetch are unaffected — see their own cadence notes
above).

## v9: Guaranteed Delivery

A single cron line has exactly one shot per day. v9 does not change what the
daily chain does — it makes sure the chain gets a chance to run every weekday by
adding two more independent triggers (systemd user timer, Windows Task Scheduler)
alongside cron, and putting one guard script in front of all three so redundant
or caught-up triggers can never run the chain twice on the same day.

**v10.1 applies the same architecture to the NIGHTLY chain** (training + research +
forward sleeves + Auto-Depot): `scripts/run_nightly_guarded.sh` guards cron 02:30,
the persistent systemd timer `equity-scout-nightly.timer` (02:35 Tue–Sat,
`Persistent=true` — a missed slot fires once at the next WSL start) and the
optional Windows task `equity-scout-nightly` (02:40 Tue–Sat, starts WSL if down;
register once via `./scripts/install_windows_task.sh`). One deliberate difference
to the daily guard: **no weekend skip** — the Saturday slot books Friday's close,
so a Sunday catch-up after a missed Saturday is wanted; the depot advance is
idempotent per panel date, so redundant runs book nothing. Marker/lock:
`.state/nightly_last_run`, `.state/nightly.lock`, log: `train.log`.

### Architecture

```
cron            18:00 Mon-Fri  ──┐
systemd timer   18:05 Mon-Fri  ──┼──▶ scripts/run_daily_guarded.sh <trigger> ──▶ scripts/daily_copilot.sh
Windows Task    18:00 Mon-Fri  ──┘         │
  (StartWhenAvailable,                     ├─ weekday guard: exit if date +%u > 5 (Sat/Sun)
   starts WSL if needed)                   ├─ flock -n on .state/daily.lock (holder time/pid/trigger recorded)
                                            ├─ skip if .state/daily_last_run is already stamped today
                                            └─ run daily_copilot.sh; stamp the marker only if it exits 0
```

Every trigger passes its own name (`cron` / `systemd` / `windows`) as `$1` to
`run_daily_guarded.sh`, so `copilot.log` always shows which path actually fired
the chain. Lock-held and weekend skips are logged too, so an unusual "why didn't
it run" is answerable from the log. The already-ran-today skip is deliberately
quiet (no log line) — it's the everyday expected case for the redundant triggers
(cron already ran, systemd's 18:05 catches nothing to catch up), not something
to diagnose; whether the day ran at all is visible from the "guarded: starting"
line and the `.state/daily_last_run` marker, not from a skip line.

### Triggers

| Trigger | Schedule | Passed as `$1` | Status |
|---|---|---|---|
| Cron | `0 18 * * 1-5` (installed via `./scripts/install_crontab.sh`) | `cron` | LIVE |
| systemd user timer | `OnCalendar=Mon..Fri 18:05`, `Persistent=true` (installed via `./scripts/install_systemd_timer.sh`) | `systemd` | LIVE, enabled |
| Windows Task Scheduler | `18:00 Mon-Fri`, `StartWhenAvailable` (XML: `scripts/windows/equity-scout-daily.xml`, installer: `./scripts/install_windows_task.sh`) | `windows` | **NOT YET REGISTERED — Needs Nico: run `./scripts/install_windows_task.sh` once** |

- systemd fires 5 minutes after cron by design — cron owns the regular slot,
  systemd is purely the catch-up layer; the guard's marker is what actually
  arbitrates, so the offset is a courtesy, not a requirement.
- systemd's `Persistent=true` catches up **exactly one** missed slot at the next
  unit start (WSL boot, or the next linger-triggered user-manager start) — it
  replays only the most recent missed occurrence, not every day the VM was off.
- The Windows task starts WSL itself
  (`wsl.exe -d Ubuntu -u nicosutheimer -- .../run_daily_guarded.sh windows`) and
  runs under Nico's interactive logon token: it fires only while he is logged
  into Windows (a locked screen is fine; logged-out or powered-off is not).

### Catch-up semantics and trade-offs

A missed 18:00/18:05 slot runs at the next WSL start instead — which can be the
next morning, not the evening. Because the guard stamps one marker per calendar
day, that catch-up run consumes the *regular* evening slot for that same day: if
WSL comes up at 08:00, the chain runs then, and the 18:00 cron trigger later that
same day finds the marker already set and skips. That day's snapshot is therefore
a morning read, not an end-of-day one.

This is a deliberate trade-off, not an oversight: v9 optimizes for "guaranteed
≥ 1 run per weekday" over "always exactly at EOD" — a morning-stale pitch beats
no pitch at all.

Weekends are never caught up. The weekday guard exits before touching the lock
or the marker on Sat/Sun, so a Persistent catch-up that happens to fire on a
Saturday (e.g. WSL started for something unrelated) still consumes systemd's own
internal stamp file — permanently forgetting Friday's miss from systemd's point
of view — but `run_daily_guarded.sh` logs it explicitly as `guarded: weekend
trigger (<trigger>) — skipped by design, missed weekday slots are not made up on
weekends`, so the loss is diagnosable in `copilot.log` instead of silently
vanishing.

### App-level idempotency

The guard only prevents the *chain* from running twice a day; individual steps
keep their own idempotency:
- **Digest:** sends at most once per day. `run_digest.py` checks
  `app_state.digest_sent_on` (a tiny key-value table,
  `src/equity_scout/state_storage.py`) before doing any work, and only sets it
  after a real delivery succeeded — a failed send never blocks the next attempt.
  `--force` overrides the guard for a manual resend.
- **Pitches:** cooldowns and idempotency keys are unchanged by v9 — they already
  prevented duplicate pitches within a cooldown window regardless of how many
  times the chain ran.

### Side effects of this installation

- `install_systemd_timer.sh` ran `loginctl enable-linger` for the user, so the
  user's systemd instance (and this timer) now starts at WSL boot rather than
  only after the first interactive login. This can keep the WSL VM resident
  longer than an on-demand session would have.
- systemd's own `Persistent=` stamp file lives in the user's persistent state
  directory on the WSL ext4 filesystem — it survives WSL restarts (unlike
  anything under `/tmp`), which is what makes the catch-up possible across
  reboots.

### Uninstalling

Each trigger is removed independently:
- **Cron:** delete the `run_daily_guarded.sh cron` line via `crontab -e` (or edit
  `install_crontab.sh`'s `CHAIN_LINE` first if you also want future re-installs
  to stay in sync).
- **systemd:** `systemctl --user disable --now equity-scout-daily.timer`, then
  delete `~/.config/systemd/user/equity-scout-daily.service` and `.timer`.
  Optionally `loginctl disable-linger $USER` to undo the linger side effect above.
- **Windows:** `schtasks.exe /delete /tn equity-scout-daily /f`.

### Deliberately not built

An external dead-man's switch (e.g. a healthchecks.io-style ping-on-success /
alert-on-silence) would need a new external service and account — Needs Nico,
parked in the backlog. The three redundant local triggers plus the catch-up
layer already cover the observed failure mode (WSL not running at 18:00); an
external watchdog would only add value if all three local triggers failed at
once, which has not been observed.

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
