# Scheduling equity-scout

`scripts/scheduled_run.sh` does one full run (yfinance over the combined universe + budget-capped
LLM theses) and writes a snapshot to `equity_scout.db`. The dashboard's history view then shows
each run over time. Everything is local and free.

Pick ONE scheduler.

## Option A — cron (simplest)

```cron
# Daily at 07:00 local time
0 7 * * * /home/nicosutheimer/private/equity-scout/scripts/scheduled_run.sh >> ~/equity-scout-cron.log 2>&1
```

Install with `crontab -e`.

## Option B — systemd user timer (survives reboots, better logging)

`~/.config/systemd/user/equity-scout.service`:
```ini
[Unit]
Description=equity-scout scheduled run

[Service]
Type=oneshot
ExecStart=/home/nicosutheimer/private/equity-scout/scripts/scheduled_run.sh
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
