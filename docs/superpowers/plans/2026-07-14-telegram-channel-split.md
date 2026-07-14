# Telegram Channel Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route pitches/alerts to an intraday chat and the daily digest to a daily chat (both optional env, fallback to the main chat), raise intraday cadence to 15 min, add digest sections + Telegram delivery.

**Architecture:** `load_telegram_config` grows two optional chat ids with fallback; `run_notify`/`run_receiver` bind the intraday chat; `build_digest` gains two pure sections and `run_digest` a chunked Telegram send; the crontab installer becomes line-managing (replace, not just append).

**Tech Stack:** stdlib urllib (existing client), pytest.

**Spec:** `docs/superpowers/specs/2026-07-14-telegram-channel-split-design.md`

---

### Task 1: Channel config + message chunking (`telegram_client.py`)

**Files:** Modify `src/equity_scout/telegram_client.py`; Test `tests/test_telegram_channels.py` (create)

- [ ] Tests: `load_telegram_config` returns `intraday_chat_id`/`daily_chat_id` falling back to
  `chat_id` when unset or malformed (malformed → stderr hint, fallback, no crash);
  `split_message` keeps texts ≤ limit, splits at line boundaries, hard-splits a single
  over-long line, round-trips content.
- [ ] Implement:

```python
def _optional_chat_id(env: dict, key: str, fallback: int) -> int:
    raw = env.get(key)
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        print(f"{key} is not an integer — falling back to COPILOT_TG_CHAT_ID.", file=sys.stderr)
        return fallback

# in load_telegram_config, before return:
    config = {"token": token, "chat_id": chat_id}
    config["intraday_chat_id"] = _optional_chat_id(env, "COPILOT_TG_CHAT_ID_INTRADAY", chat_id)
    config["daily_chat_id"] = _optional_chat_id(env, "COPILOT_TG_CHAT_ID_DAILY", chat_id)
    return config

TELEGRAM_TEXT_LIMIT = 4096

def split_message(text: str, limit: int = 4000) -> list[str]:
    """Telegram caps sendMessage at 4096 chars; split at line boundaries (hard-split a
    single over-long line) so the daily digest arrives complete instead of erroring."""

def send_long_message(token: str, chat_id: int, text: str) -> int:
    """send_message per chunk; returns the LAST message_id."""
```

- [ ] Run tests, commit `feat(telegram): channel config with fallbacks + message chunking`.

### Task 2: Route notify + receiver to the intraday chat

**Files:** Modify `scripts/run_notify.py` (both senders: `config["intraday_chat_id"]`),
`scripts/run_receiver.py` (edit closure targets `config["intraday_chat_id"]`).

- [ ] Both scripts read the routed id with `config.get("intraday_chat_id", config["chat_id"])`
  so a stale config dict (tests, dry-run) still works.
- [ ] Full suite green; commit `feat(telegram): route pitches/alerts to intraday chat`.

### Task 3: Digest sections + Telegram delivery

**Files:** Modify `src/equity_scout/digest.py`, `scripts/run_digest.py`; Test `tests/test_digest_sections.py` (create)

- [ ] Tests (pure): alerts section renders ticker+reasons and is omitted when empty;
  opportunities section renders top-N by composite with in-zone/value marks, omitted when
  empty; ordering: opportunities before status blocks, alerts right after header.
- [ ] Implement `build_digest(..., alerts_today: list[dict] | None = None,
  opportunities: list[dict] | None = None)`; sections:

```
📌 Heute aufgefallen
- KHC: Kongress-Käufe, Insider-Käufe (Form 4) (3 Käufer)

🎯 Chancen im Blick
- NVDA  Composite 0.81  [in Zone]  [unterbewertet]
```

  (labels reuse `_SOURCE_LABEL`; "unterbewertet" = `value_gap > 0`, "in Zone" = `in_zone`).
- [ ] `run_digest.py`: fetch `load_alerts(db, limit=50)` filtered to the last 24 h and
  `load_latest_watchlist(db)` top 3 by composite; after SMTP/stdout, if
  `load_telegram_config` yields config → `send_long_message(token, daily_chat_id, text)`
  (failure = stderr warning, never a crash).
- [ ] Full suite green; commit `feat(digest): today-sections + Telegram daily-chat delivery`.

### Task 4: Cadence 15 min + line-managing installer

**Files:** Modify `scripts/install_crontab.sh`, `docs/scheduling.md`.

- [ ] `INTRADAY_LINE` becomes `*/15 * * * 1-5 …`; installer filters out any existing line
  containing a managed script filename before re-adding canonical lines:

```bash
MANAGED_SCRIPTS="daily_copilot.sh receiver_keepalive.sh intraday_copilot.sh nightly_train.sh nightly_prefetch.sh"
for script in $MANAGED_SCRIPTS; do
  current="$(printf '%s\n' "$current" | grep -vF "/scripts/${script}" || true)"
done
```

  then the existing append loop adds all five canonical lines. Output: report replaced count.
- [ ] `bash -n`, scheduling.md cadence note (why 15 not 10: yfinance ~15-min delay), commit
  `feat(cron): 15-min intraday cadence + line-managing installer`.

### Task 5: Gate + docs + outcome

- [ ] `uv run pytest -p no:warnings` all green, `uv run ruff check .` clean, `bash -n` scripts.
- [ ] README Telegram env vars section, spec/plan outcome, report Needs-Nico steps.

---

## Outcome (2026-07-14, executed same session)

**Shipped** (commits `828dc17..`): channel config with fallbacks + `split_message`/
`send_long_message` chunking (7 tests), pitches/alerts routed to the intraday chat
(receiver outcome-edits follow), digest day-sections ("Heute aufgefallen" +
"Chancen im Blick", 5 tests) + Telegram daily-chat delivery (SMTP/stdout unchanged),
15-min intraday cadence with a line-managing crontab installer (old `*/30` line gets
replaced, not duplicated). Digest smoke on the production DB rendered today's 21
congress/voices alerts correctly.

**Deviations:** two pre-existing tests asserted the old config shape / stdout wording —
updated with a channel-split note. Cadence is 15 min, not literally 10 ("oder so"-Spielraum):
yfinance prices are ~15 min delayed, faster polling adds only rate-limit load.

**Finding (pre-existing, NOT fixed, out of scope):** voices ticker resolution matched
"Micron" to MSN instead of MU in one live alert — the deterministic name→ticker boundary
in `evidence/voices.py` deserves a look.

**Needs Nico (one-time, ~5 min):** create the two chats (e.g. two groups with the bot,
or keep everything in the private chat and skip the extra vars), set
`COPILOT_TG_BOT_TOKEN`, `COPILOT_TG_CHAT_ID`, `COPILOT_TG_CHAT_ID_INTRADAY`,
`COPILOT_TG_CHAT_ID_DAILY` in `.env`, re-run `./scripts/install_crontab.sh`.
