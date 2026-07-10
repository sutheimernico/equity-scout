# Scheduling equity-scout

Two layers of automation, both cron-driven and local/free:

1. **`scripts/daily_copilot.sh`** — the full unattended copilot chain:
   (Mondays: screener first) → radar → evidence collectors → notify (pitches +
   evidence alerts to Telegram) → score watchlist → resolve predictions → resolve
   evidence → lanes → digest. Every step degrades independently and appends to
   `copilot.log`; a failed step never blocks the rest.
2. **`scripts/receiver_keepalive.sh`** — restarts the Telegram decision receiver
   (under `flock -n`, single instance) so buy/pass/later buttons keep working after
   a reboot. Quiet no-op without Telegram config.

`scripts/scheduled_run.sh` remains the standalone screener run (also called by the
Monday branch of the chain).

## Installed crontab (2026-07-10)

```cron
# forward-paper strategies (pre-existing)
0 23 * * 1-5 cd /home/nicosutheimer/private/equity-scout && .venv/bin/python scripts/run_forward_paper.py --refresh >> /home/nicosutheimer/private/equity-scout/forward.log 2>&1
# daily copilot chain — 18:00 local, US market is open so radar zones use live prices
0 18 * * 1-5 /home/nicosutheimer/private/equity-scout/scripts/daily_copilot.sh >> /home/nicosutheimer/private/equity-scout/copilot.log 2>&1
# receiver keepalive — flock guarantees a single instance; no-op without Telegram env
*/5 * * * * flock -n /tmp/equity-scout-receiver.lock /home/nicosutheimer/private/equity-scout/scripts/receiver_keepalive.sh >> /home/nicosutheimer/private/equity-scout/receiver.log 2>&1
```

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
