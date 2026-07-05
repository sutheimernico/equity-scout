# Trading Copilot — Phase 2: Notifications & Decision Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Watchlist entries above threshold become German pitch messages on Telegram with [Kaufen]/[Ablehnen]/[Später] buttons, mirrored in a dashboard inbox and a daily e-mail digest; a local long-polling receiver records Nico's one-tap decisions.

**Architecture:** Generic Telegram primitives lifted from tap-approve (stdlib `urllib`, DI seams, fail-safe config) into a new `telegram_client.py`. A `pitches` SQLite table (per-concern storage module, defensive migration idiom) is the single source of truth for inbox state and per-ticker cooldowns. `notify.py` selects candidates (in-zone + threshold + cooldown) from the latest watchlist and orchestrates pitch creation + sending; `scripts/run_receiver.py` long-polls for button callbacks; `digest.py` renders/sends the daily e-mail via `smtplib` behind a transport seam. Pitch text: local Ollama via the existing `chat.ask_ollama` seam with a deterministic fallback (mirrors `analysis.py`'s unavailable-prefix convention) — the LLM interprets computed numbers, never forecasts.

**Tech Stack:** Python 3.11 stdlib (`urllib.request`, `smtplib`, `sqlite3`), FastAPI, pytest, ruff. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-04-trading-copilot-design.md` (§6, §4.2)
**Builds on:** Phase 1 (`radar_storage.load_latest_watchlist`, `WatchlistEntry` dict shape incl. `readings`, `zone_note`, `breakdown`)

**Conventions that bind every task** (unchanged from Phase 1):
- Code/docstrings/tests English; user-facing strings German with correct umlauts (ADR 0001).
- Pure functions + DI seams; network only in thin, injected transport functions; `created_at`/`decided_at` injected by callers.
- All imports top-of-file (ruff E402). Gate before EVERY commit: `.venv/bin/python -m pytest && ruff check .` (use `-v` or exit code, never stack `-q`). Suite baseline: 241 passed.
- Env config per module via `os.environ.get`, fail-safe parsing (missing → `None` + stderr hint, never crash) — the tap-approve `load_config` pattern.
- Tests: DI fakes, no monkeypatching HTTP internals, no network, `tmp_path` SQLite.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/equity_scout/telegram_client.py` | create | generic Telegram API: send/edit/answer/get_updates + inline keyboard + decision extraction |
| `src/equity_scout/pitch.py` | create | German pitch text from a watchlist entry (Ollama seam + deterministic fallback) |
| `src/equity_scout/inbox_storage.py` | create | `pitches` table: create/decide/load, cooldown lookup |
| `src/equity_scout/notify.py` | create | candidate selection + orchestration (create pitch → send Telegram) |
| `src/equity_scout/digest.py` | create | daily digest text + SMTP send behind transport seam |
| `scripts/run_notify.py` | create | CLI: latest watchlist → pitches + Telegram sends |
| `scripts/run_receiver.py` | create | CLI: long-polling loop recording button decisions |
| `scripts/run_digest.py` | create | CLI: render + send the daily digest e-mail |
| `src/equity_scout/api.py` | modify | `GET /api/inbox`, `POST /api/inbox/{pitch_id}/decision` |
| `tests/test_telegram_client.py` | create | keyboard/extraction/polling with canned updates |
| `tests/test_pitch.py` | create | pitch text + fallback |
| `tests/test_inbox_storage.py` | create | round-trip, transitions, cooldown |
| `tests/test_notify.py` | create | selection rules + orchestration with fakes |
| `tests/test_digest.py` | create | digest rendering + fake transport |
| `tests/test_run_receiver.py` | create | update-processing loop with fakes |
| `tests/test_api.py` | modify | inbox endpoints |

Env vars (documented in `.env.example`, added in Task 8): `COPILOT_TG_BOT_TOKEN`, `COPILOT_TG_CHAT_ID`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `DIGEST_TO`. All live sends are **Needs Nico** (BotFather token, SMTP creds) — every task is fully testable without them via DI fakes.

---

### Task 1: Telegram client primitives

**Files:**
- Create: `src/equity_scout/telegram_client.py`
- Test: `tests/test_telegram_client.py`

Lift the generic primitives from tap-approve (`~/private/tap-approve/src/tap_approve.py` — read it once for reference, but the code below is self-contained), generalized from allow/deny to arbitrary action sets.

- [x] **Step 1: Write the failing tests**

```python
"""Telegram client tests — pure logic + DI'd transport, no network."""
from __future__ import annotations

from equity_scout.telegram_client import (
    build_decision_keyboard,
    extract_decision,
    load_telegram_config,
    poll_updates,
)

CHAT_ID = 4242


def _update(update_id: int, data: str, from_id: int = CHAT_ID) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {"id": f"cb{update_id}", "from": {"id": from_id}, "data": data},
    }


def test_build_decision_keyboard_has_three_action_buttons():
    kb = build_decision_keyboard(7)
    buttons = kb["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == ["buy:7", "pass:7", "later:7"]
    assert "Kaufen" in buttons[0]["text"]


def test_extract_decision_accepts_valid_actions_only():
    assert extract_decision(_update(1, "buy:7"), CHAT_ID) == ("buy", 7, "cb1")
    assert extract_decision(_update(2, "explode:7"), CHAT_ID) is None
    assert extract_decision(_update(3, "buy:notanint"), CHAT_ID) is None
    assert extract_decision({"update_id": 4}, CHAT_ID) is None


def test_extract_decision_rejects_wrong_sender():
    assert extract_decision(_update(1, "buy:7", from_id=999), CHAT_ID) is None


def test_poll_updates_advances_offset_over_all_updates():
    batches = [[_update(10, "buy:1"), _update(11, "nonsense")], []]
    calls: list[int | None] = []

    def fake_get_updates(offset):
        calls.append(offset)
        return batches.pop(0) if batches else []

    decisions, offset = poll_updates(fake_get_updates, offset=None, chat_id=CHAT_ID)
    assert decisions == [("buy", 1, "cb10")]
    assert offset == 12  # advanced past BOTH updates, including the non-matching one
    assert calls == [None]


def test_load_telegram_config_fail_safe(capsys):
    assert load_telegram_config({}) is None
    assert (
        load_telegram_config({"COPILOT_TG_BOT_TOKEN": "t", "COPILOT_TG_CHAT_ID": "x"}) is None
    )
    assert "COPILOT_TG_CHAT_ID" in capsys.readouterr().err
    cfg = load_telegram_config({"COPILOT_TG_BOT_TOKEN": "t", "COPILOT_TG_CHAT_ID": "42"})
    assert cfg == {"token": "t", "chat_id": 42}
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_telegram_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.telegram_client'`.

- [x] **Step 3: Write the implementation**

```python
"""Generic Telegram Bot API client for the copilot inbox.

Lifted from tap-approve's proven primitives (stdlib urllib, no dependencies) and
generalized from allow/deny to the buy/pass/later action set. Design rules kept:
- transport is a thin function; all logic is pure and takes injected callables
- fail-safe config: missing/malformed env yields None + stderr hint, never a crash
- the receiver consumes EVERY update's offset, matching or not, so stale button
  presses can't wedge the queue
Plain text messages only (no parse_mode), so no escaping is needed.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from collections.abc import Callable

API = "https://api.telegram.org/bot{token}/{method}"
ACTIONS = ("buy", "pass", "later")
_BUTTON_LABELS = {"buy": "✅ Kaufen", "pass": "❌ Ablehnen", "later": "⏸ Später"}


def load_telegram_config(env: dict) -> dict | None:
    """{"token": str, "chat_id": int} or None (with a stderr hint) if unusable."""
    token = env.get("COPILOT_TG_BOT_TOKEN")
    raw_chat = env.get("COPILOT_TG_CHAT_ID")
    if not token or not raw_chat:
        return None
    try:
        chat_id = int(raw_chat)
    except ValueError:
        print("COPILOT_TG_CHAT_ID is not an integer — Telegram disabled.", file=sys.stderr)
        return None
    return {"token": token, "chat_id": chat_id}


def _api(token: str, method: str, params: dict, timeout: float = 35.0) -> dict:
    """Single POST to the Bot API. No retry — callers decide what failure means."""
    request = urllib.request.Request(
        API.format(token=token, method=method),
        data=json.dumps(params).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_decision_keyboard(pitch_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": _BUTTON_LABELS[action], "callback_data": f"{action}:{pitch_id}"}
                for action in ACTIONS
            ]
        ]
    }


def send_message(token: str, chat_id: int, text: str, keyboard: dict | None = None) -> int:
    """Returns the Telegram message_id (stored so the receiver can edit later)."""
    params: dict = {"chat_id": chat_id, "text": text}
    if keyboard is not None:
        params["reply_markup"] = keyboard
    return int(_api(token, "sendMessage", params)["result"]["message_id"])


def edit_message(token: str, chat_id: int, message_id: int, text: str) -> None:
    _api(token, "editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text})


def answer_callback(token: str, callback_query_id: str, text: str) -> None:
    _api(token, "answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})


def get_updates(token: str, offset: int | None, long_poll: int = 20) -> list[dict]:
    params: dict = {"timeout": long_poll, "allowed_updates": ["callback_query"]}
    if offset is not None:
        params["offset"] = offset
    return _api(token, "getUpdates", params, timeout=long_poll + 5)["result"]


def extract_decision(update: dict, chat_id: int) -> tuple[str, int, str] | None:
    """(action, pitch_id, callback_query_id) — or None for anything not a valid,
    same-chat buy/pass/later press. The sender check is the security gate."""
    cq = update.get("callback_query")
    if not cq or cq.get("from", {}).get("id") != chat_id:
        return None
    action, _, raw_id = str(cq.get("data", "")).partition(":")
    if action not in ACTIONS:
        return None
    try:
        pitch_id = int(raw_id)
    except ValueError:
        return None
    return action, pitch_id, str(cq.get("id", ""))


def poll_updates(
    fetch: Callable[[int | None], list[dict]], offset: int | None, chat_id: int
) -> tuple[list[tuple[str, int, str]], int | None]:
    """One fetch round: returns (decisions, next_offset). Consumes every update."""
    decisions: list[tuple[str, int, str]] = []
    for update in fetch(offset):
        update_id = update.get("update_id")
        if update_id is None:
            continue
        offset = int(update_id) + 1
        decision = extract_decision(update, chat_id)
        if decision is not None:
            decisions.append(decision)
    return decisions, offset
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_telegram_client.py -v` — expected: all PASS.

- [x] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/telegram_client.py tests/test_telegram_client.py
git commit -m "feat: add generic telegram client with buy/pass/later decisions"
```

**Outcome:** Implemented verbatim, no deviations. Gate: 246 passed (241 baseline + 5), ruff clean. Commit `93d6cd5`. Review fix `a125a0e`: `TelegramError` raised by `_api` on HTTP errors (body read for Telegram's reason) and on `{"ok": false}` payloads; `extract_decision` now rejects negative pitch ids; boundary tests for `"buy:"`/`"buy:7:extra"`/`"buy:-7"` added; the two `_api` error tests monkeypatch `urllib.request.urlopen` — sanctioned because `_api` IS the transport.

---

### Task 2: Pitch text builder

**Files:**
- Create: `src/equity_scout/pitch.py`
- Test: `tests/test_pitch.py`

- [x] **Step 1: Write the failing tests**

```python
"""Pitch builder tests. LLM seam injected; fallback must be deterministic."""
from __future__ import annotations

from equity_scout.chat import ChatError
from equity_scout.pitch import PITCH_LLM_UNAVAILABLE_PREFIX, build_pitch

ENTRY = {
    "ticker": "EXE",
    "name": "Example Corp",
    "bucket": "defensive",
    "price": 90.72,
    "entry_zone_low": 84.77,
    "entry_zone_high": 103.01,
    "in_zone": True,
    "proximity": -0.119,
    "composite": 0.592,
    "zone_note": "Kurs in der Entry-Zone (84.77–103.01).",
    "breakdown": {"value": 0.8, "quality": 0.9, "momentum": 0.4, "growth": 0.5},
    "readings": [
        {"name": "dip_quality", "score": 0.75, "reason": "Kurs -22.1 % vom 52-Wochen-Hoch..."},
        {"name": "value_gap", "score": 0.72, "reason": "Kurs -8.3 % unter dem 200-Tage-Schnitt..."},
        {"name": "momentum", "score": 0.16, "reason": "Kurs unter dem 20-Tage-Schnitt..."},
    ],
}


def test_build_pitch_uses_llm_text_and_appends_facts():
    pitch = build_pitch(ENTRY, ask=lambda question, context: "Kurzer LLM-Text.")
    assert pitch.startswith("📈 EXE — Example Corp")
    assert "Kurzer LLM-Text." in pitch
    assert "Score 59/100" in pitch
    assert "84.77" in pitch and "103.01" in pitch
    assert "Keine Anlageberatung" in pitch


def test_build_pitch_falls_back_deterministically_on_chat_error():
    def broken(question, context):
        raise ChatError("ollama down")

    pitch = build_pitch(ENTRY, ask=broken)
    assert PITCH_LLM_UNAVAILABLE_PREFIX in pitch
    assert "52-Wochen-Hoch" in pitch  # readings' reasons carry the pitch instead
    assert "Score 59/100" in pitch


def test_build_pitch_stays_under_telegram_limit():
    entry = dict(ENTRY)
    entry["readings"] = [
        {"name": "dip_quality", "score": 0.7, "reason": "R" * 3000},
        {"name": "value_gap", "score": 0.7, "reason": "V" * 3000},
        {"name": "momentum", "score": 0.7, "reason": "M" * 3000},
    ]
    pitch = build_pitch(entry, ask=lambda q, c: "X" * 5000)
    assert len(pitch) <= 4000  # Telegram hard limit is 4096; headroom for edits
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pitch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.pitch'`.

- [x] **Step 3: Write the implementation**

```python
"""German pitch text for one watchlist entry.

The LLM (local Ollama via chat.ask_ollama) INTERPRETS the computed numbers into
two readable sentences — it must never forecast or rank (same guardrail as
analysis.py / chat.py). Every failure degrades to a deterministic fallback built
from the sub-signal reasons, marked with PITCH_LLM_UNAVAILABLE_PREFIX (mirrors
analysis.THESIS_UNAVAILABLE_PREFIX): missing Ollama never blocks a notification.
"""
from __future__ import annotations

from collections.abc import Callable

from equity_scout.chat import ChatError, ask_ollama

PITCH_LLM_UNAVAILABLE_PREFIX = "(Automatische Kurzeinschätzung nicht verfügbar)"
_LIMIT = 4000  # Telegram hard limit 4096; keep headroom for the decision edit suffix

_QUESTION = (
    "Fasse in maximal zwei deutschen Sätzen zusammen, was dieses Unternehmen macht und "
    "warum der aktuelle Kurs laut den Kennzahlen unten in einer Einstiegszone liegt. "
    "Keine Prognosen, keine Kursziele, keine Empfehlung — nur Einordnung der Zahlen."
)


def _ask_default(question: str, context: str) -> str:
    return ask_ollama(question, context)


def _fact_block(entry: dict) -> str:
    lines = [
        f"Score {round(entry['composite'] * 100)}/100 · Bucket: {entry['bucket']}",
        f"Kurs {entry['price']:.2f} · Zone {entry['entry_zone_low']:.2f}–"
        f"{entry['entry_zone_high']:.2f}",
        entry["zone_note"],
    ]
    for reading in entry["readings"]:
        lines.append(f"• {reading['reason']}")
    return "\n".join(lines)


def build_pitch(entry: dict, ask: Callable[[str, str], str] = _ask_default) -> str:
    """Header + LLM interpretation (or fallback) + fact block + disclaimer."""
    header = f"📈 {entry['ticker']} — {entry['name']}"
    facts = _fact_block(entry)
    try:
        summary = ask(_QUESTION, facts).strip()
    except ChatError:
        summary = f"{PITCH_LLM_UNAVAILABLE_PREFIX} — Signalgründe siehe unten."
    text = f"{header}\n\n{summary}\n\n{facts}\n\nKeine Anlageberatung."
    if len(text) > _LIMIT:
        text = text[: _LIMIT - 1] + "…"
    return text
```

Note: check `chat.py`'s actual `ChatError`/`ask_ollama` names and signatures before writing (`ask_ollama(question, context, model=..., host=..., timeout=...)` per the API map); adapt the `_ask_default` wrapper minimally if reality differs — the `ask` seam must stay `(question, context) -> str`.

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pitch.py -v` — expected: all PASS.

- [x] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/pitch.py tests/test_pitch.py
git commit -m "feat: add pitch builder with ollama seam and deterministic fallback"
```

**Outcome:** `chat.ask_ollama`'s real signature matches the plan's assumption exactly (`ask_ollama(question, context, *, model, host, timeout)`), so `_ask_default` needed no adaptation. One deviation from the plan snippet: `_fact_block` used `f"Score {round(...):.0f}/100"` — the `:.0f` on an already-`round()`-ed int is redundant (Python happily formats an int with a float spec, so it wasn't a bug, just noise) and inconsistent with Task 6's `digest.py` snippet, which uses the plain-int form. Simplified to `f"Score {round(...)}/100"` per the task instructions, verified `round(0.592*100) == 59` still yields "Score 59/100", and kept test + code aligned. Gate: 249 passed (246 baseline + 3), ruff clean. Commit `92a573b`. Review fix `a125a0e`: the plan's tail-truncation silently dropped the disclaimer — `build_pitch` now truncates only the middle (summary + facts) so header and "Keine Anlageberatung." always survive (limit test asserts both at the 4000 boundary); fallback says "Keine Signaldetails verfügbar." when `readings` is empty; `_LIMIT` comment documents Telegram's UTF-16 counting. Gate after fix: 253 passed, ruff clean.

---

### Task 3: Inbox persistence (`inbox_storage.py`)

**Files:**
- Create: `src/equity_scout/inbox_storage.py`
- Test: `tests/test_inbox_storage.py`

- [x] **Step 1: Write the failing tests**

```python
"""Inbox storage: pitch lifecycle + cooldown lookups (tmp_path SQLite)."""
from __future__ import annotations

from equity_scout.inbox_storage import (
    create_pitch,
    decide_pitch,
    init_inbox_db,
    last_pitch_at,
    load_pitches,
    set_message_id,
)

T0 = "2026-07-05T10:00:00+00:00"
T1 = "2026-07-05T11:00:00+00:00"


def _pitch_row(db, ticker="EXE", created_at=T0):
    return create_pitch(
        db,
        ticker=ticker,
        watchlist_id=1,
        price=90.72,
        composite=0.592,
        zone_low=84.77,
        zone_high=103.01,
        pitch="Pitch-Text",
        created_at=created_at,
    )


def test_create_and_load_open_pitch(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _pitch_row(db)
    pitches = load_pitches(db)
    assert len(pitches) == 1
    p = pitches[0]
    assert (p["id"], p["ticker"], p["status"], p["decided_at"]) == (pitch_id, "EXE", "open", None)


def test_decide_pitch_transitions_only_from_open(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _pitch_row(db)
    assert decide_pitch(db, pitch_id, "buy", decided_at=T1) is True
    assert decide_pitch(db, pitch_id, "pass", decided_at=T1) is False  # already decided
    assert decide_pitch(db, 999, "buy", decided_at=T1) is False  # unknown id
    p = load_pitches(db)[0]
    assert (p["status"], p["decided_at"]) == ("buy", T1)


def test_decide_pitch_rejects_unknown_action(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _pitch_row(db)
    assert decide_pitch(db, pitch_id, "explode", decided_at=T1) is False
    assert load_pitches(db)[0]["status"] == "open"


def test_last_pitch_at_per_ticker(tmp_path):
    db = str(tmp_path / "inbox.db")
    init_inbox_db(db)
    assert last_pitch_at(db, "EXE") is None
    _pitch_row(db, created_at=T0)
    _pitch_row(db, created_at=T1)
    assert last_pitch_at(db, "EXE") == T1
    assert last_pitch_at(db, "OTHER") is None


def test_set_message_id_round_trip(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _pitch_row(db)
    set_message_id(db, pitch_id, 555)
    assert load_pitches(db)[0]["telegram_message_id"] == 555
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_inbox_storage.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [x] **Step 3: Write the implementation**

```python
"""SQLite persistence for the decision inbox (one pitch = one notification).

Same idiom as radar_storage.py: raw sqlite3, idempotent init, per-function
connections. `status` lifecycle: open -> buy | pass | later (single transition,
enforced in decide_pitch's WHERE clause — concurrency-safe by construction).
last_pitch_at() is the cooldown source: notify.py never re-pitches a ticker
inside its cooldown window regardless of the previous pitch's outcome.
"""
from __future__ import annotations

import sqlite3

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.telegram_client import ACTIONS

_COLUMNS = (
    "id, created_at, ticker, watchlist_id, price, composite, zone_low, zone_high, "
    "pitch, status, decided_at, telegram_message_id"
)


def init_inbox_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pitches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                watchlist_id INTEGER,
                price REAL NOT NULL,
                composite REAL NOT NULL,
                zone_low REAL NOT NULL,
                zone_high REAL NOT NULL,
                pitch TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                decided_at TEXT,
                telegram_message_id INTEGER
            )"""
        )


def create_pitch(
    db_path: str,
    *,
    ticker: str,
    watchlist_id: int | None,
    price: float,
    composite: float,
    zone_low: float,
    zone_high: float,
    pitch: str,
    created_at: str,
) -> int:
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO pitches (created_at, ticker, watchlist_id, price, composite,"
            " zone_low, zone_high, pitch) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (created_at, ticker, watchlist_id, price, composite, zone_low, zone_high, pitch),
        )
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)


def decide_pitch(db_path: str, pitch_id: int, action: str, *, decided_at: str) -> bool:
    """True iff the pitch existed, was still open, and `action` is valid."""
    if action not in ACTIONS:
        return False
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE pitches SET status = ?, decided_at = ? WHERE id = ? AND status = 'open'",
            (action, decided_at, pitch_id),
        )
        return cursor.rowcount == 1


def set_message_id(db_path: str, pitch_id: int, message_id: int) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE pitches SET telegram_message_id = ? WHERE id = ?", (message_id, pitch_id)
        )


def last_pitch_at(db_path: str, ticker: str) -> str | None:
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(created_at) FROM pitches WHERE ticker = ?", (ticker,)
        ).fetchone()
    return row[0] if row and row[0] else None


def load_pitches(db_path: str = DEFAULT_DB_PATH, limit: int = 100) -> list[dict]:
    """Newest first, open pitches before decided ones."""
    init_inbox_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM pitches"
            " ORDER BY (status = 'open') DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    keys = [k.strip() for k in _COLUMNS.split(",")]
    return [dict(zip(keys, row)) for row in rows]
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_inbox_storage.py -v` — expected: all PASS.

- [x] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/inbox_storage.py tests/test_inbox_storage.py
git commit -m "feat: add decision-inbox persistence with pitch lifecycle and cooldown"
```

**Outcome:** Implemented verbatim, no deviations. Gate: 258 passed (253 baseline + 5), ruff clean. Commit `a49414b`. Review fix (shared commit, see Task 4 outcome): value columns pinned field-by-field in `test_create_and_load_open_pitch` (zone_low/zone_high/price/composite — a swapped pair no longer survives the suite); `set_message_id` now calls `init_inbox_db` first like every other function in the module; `last_pitch_at` documents the lexicographic-MAX invariant (all writers must produce UTC "+00:00" ISO strings, never mixed offsets).

---

### Task 4: Notification orchestration (`notify.py` + `scripts/run_notify.py`)

**Files:**
- Create: `src/equity_scout/notify.py`, `scripts/run_notify.py`
- Test: `tests/test_notify.py`

- [x] **Step 1: Write the failing tests**

```python
"""Candidate selection rules + notify orchestration with fakes end-to-end."""
from __future__ import annotations

from equity_scout.inbox_storage import create_pitch, load_pitches
from equity_scout.notify import notify_watchlist, select_candidates

NOW = "2026-07-05T12:00:00+00:00"


def _entry(ticker: str, composite: float = 0.6, in_zone: bool = True) -> dict:
    return {
        "ticker": ticker,
        "name": f"{ticker} Corp",
        "bucket": "core",
        "price": 100.0,
        "entry_zone_low": 95.0,
        "entry_zone_high": 105.0,
        "in_zone": in_zone,
        "proximity": -0.05,
        "composite": composite,
        "zone_note": "Kurs in der Entry-Zone (95.00–105.00).",
        "breakdown": {"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5},
        "readings": [{"name": "dip_quality", "score": 0.5, "reason": "Grund."}],
    }


def test_select_candidates_filters_zone_threshold_cooldown():
    watchlist = {
        "created_at": NOW,
        "entries": [
            _entry("YES"),
            _entry("COLD"),
            _entry("LOW", composite=0.2),
            _entry("OUT", in_zone=False),
        ],
    }
    picked = select_candidates(
        watchlist,
        last_pitch_at=lambda t: "2026-07-04T12:00:00+00:00" if t == "COLD" else None,
        threshold=0.45,
        cooldown_days=7,
        now=NOW,
    )
    assert [e["ticker"] for e in picked] == ["YES"]


def test_select_candidates_repitches_after_cooldown():
    watchlist = {"created_at": NOW, "entries": [_entry("COLD")]}
    picked = select_candidates(
        watchlist,
        last_pitch_at=lambda t: "2026-06-20T12:00:00+00:00",
        threshold=0.45,
        cooldown_days=7,
        now=NOW,
    )
    assert [e["ticker"] for e in picked] == ["COLD"]


def test_notify_watchlist_creates_pitches_and_sends(tmp_path):
    db = str(tmp_path / "inbox.db")
    watchlist = {"created_at": NOW, "entries": [_entry("YES"), _entry("LOW", composite=0.1)]}
    sent: list[tuple[int, str]] = []

    def fake_send(pitch_id: int, text: str) -> int:
        sent.append((pitch_id, text))
        return 500 + pitch_id

    count = notify_watchlist(
        db,
        watchlist,
        build=lambda entry: f"PITCH {entry['ticker']}",
        send=fake_send,
        threshold=0.45,
        cooldown_days=7,
        now=NOW,
    )
    assert count == 1
    pitches = load_pitches(db)
    assert len(pitches) == 1
    assert pitches[0]["ticker"] == "YES"
    assert pitches[0]["telegram_message_id"] == 501 + pitches[0]["id"] - 1  # 500 + pitch_id
    assert sent == [(pitches[0]["id"], "PITCH YES")]


def test_notify_watchlist_without_send_still_creates_inbox_rows(tmp_path):
    db = str(tmp_path / "inbox.db")
    watchlist = {"created_at": NOW, "entries": [_entry("YES")]}
    count = notify_watchlist(
        db, watchlist, build=lambda e: "P", send=None, threshold=0.45, cooldown_days=7, now=NOW
    )
    assert count == 1
    assert load_pitches(db)[0]["telegram_message_id"] is None


def test_notify_respects_cooldown_from_own_previous_run(tmp_path):
    db = str(tmp_path / "inbox.db")
    create_pitch(
        db, ticker="YES", watchlist_id=None, price=1, composite=0.5, zone_low=1,
        zone_high=2, pitch="alt", created_at="2026-07-04T12:00:00+00:00",
    )
    watchlist = {"created_at": NOW, "entries": [_entry("YES")]}
    count = notify_watchlist(
        db, watchlist, build=lambda e: "P", send=None, threshold=0.45, cooldown_days=7, now=NOW
    )
    assert count == 0
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_notify.py -v` — expected: `ModuleNotFoundError`.

- [x] **Step 3: Write the implementation**

```python
"""Notification rules + orchestration: watchlist -> inbox pitches -> Telegram.

Selection is deliberately strict (spec §6: notify ONLY when genuinely attractive):
in_zone AND composite >= threshold AND ticker outside its cooldown window.
Cooldown compares ISO-8601 strings via date arithmetic (timezone-aware).
The send seam is (pitch_id, text) -> telegram_message_id so tests and the
no-token dry mode never touch the network; send=None records inbox rows only.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from equity_scout.inbox_storage import create_pitch, last_pitch_at as _last_pitch_at
from equity_scout.inbox_storage import set_message_id

DEFAULT_THRESHOLD = 0.45
DEFAULT_COOLDOWN_DAYS = 7


def _inside_cooldown(last_iso: str | None, now_iso: str, cooldown_days: int) -> bool:
    if last_iso is None:
        return False
    last = datetime.fromisoformat(last_iso)
    now = datetime.fromisoformat(now_iso)
    return now - last < timedelta(days=cooldown_days)


def select_candidates(
    watchlist: dict,
    *,
    last_pitch_at: Callable[[str], str | None],
    threshold: float,
    cooldown_days: int,
    now: str,
) -> list[dict]:
    return [
        entry
        for entry in watchlist.get("entries", [])
        if entry["in_zone"]
        and entry["composite"] >= threshold
        and not _inside_cooldown(last_pitch_at(entry["ticker"]), now, cooldown_days)
    ]


def notify_watchlist(
    db_path: str,
    watchlist: dict,
    *,
    build: Callable[[dict], str],
    send: Callable[[int, str], int] | None,
    threshold: float = DEFAULT_THRESHOLD,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    now: str,
) -> int:
    """Create inbox pitches (and send them, if a sender is configured).

    Returns the number of pitches created. The inbox row is written BEFORE the
    send so a Telegram failure can never lose a pitch — the dashboard inbox is
    the source of truth; Telegram is a delivery channel.
    """
    candidates = select_candidates(
        watchlist,
        last_pitch_at=lambda ticker: _last_pitch_at(db_path, ticker),
        threshold=threshold,
        cooldown_days=cooldown_days,
        now=now,
    )
    for entry in candidates:
        text = build(entry)
        pitch_id = create_pitch(
            db_path,
            ticker=entry["ticker"],
            watchlist_id=entry.get("watchlist_id"),
            price=entry["price"],
            composite=entry["composite"],
            zone_low=entry["entry_zone_low"],
            zone_high=entry["entry_zone_high"],
            pitch=text,
            created_at=now,
        )
        if send is not None:
            set_message_id(db_path, pitch_id, send(pitch_id, text))
    return len(candidates)
```

And `scripts/run_notify.py`:

```python
"""Notify CLI: latest watchlist -> inbox pitches -> Telegram (if configured).

Usage:
    python scripts/run_notify.py [--db equity_scout.db] [--threshold 0.45]
        [--cooldown-days 7] [--dry-run]

Without COPILOT_TG_BOT_TOKEN/COPILOT_TG_CHAT_ID (or with --dry-run) pitches are
only written to the inbox — nothing is sent. Run scripts/run_radar.py first.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.notify import DEFAULT_COOLDOWN_DAYS, DEFAULT_THRESHOLD, notify_watchlist
from equity_scout.pitch import build_pitch
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.telegram_client import (
    build_decision_keyboard,
    load_telegram_config,
    send_message,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--cooldown-days", type=int, default=DEFAULT_COOLDOWN_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    watchlist = load_latest_watchlist(args.db)
    if watchlist is None:
        print("No watchlist found — run scripts/run_radar.py first.", file=sys.stderr)
        return 1

    config = None if args.dry_run else load_telegram_config(dict(os.environ))
    if config is None:
        send = None
        print("Telegram not configured — writing inbox pitches only.")
    else:
        def send(pitch_id: int, text: str) -> int:
            return send_message(
                config["token"], config["chat_id"], text, build_decision_keyboard(pitch_id)
            )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    count = notify_watchlist(
        args.db, watchlist, build=build_pitch, send=send,
        threshold=args.threshold, cooldown_days=args.cooldown_days, now=now,
    )
    print(f"Pitches created: {count}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add CLI tests to `tests/test_notify.py` following the `test_run_radar.py` main()-pattern (monkeypatched `sys.argv` + seeded watchlist via `radar_storage.save_watchlist`, empty env → inbox-only path; assert exit codes, stdout, and that NO network is attempted).

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_notify.py -v` — expected: all PASS.

- [x] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/notify.py scripts/run_notify.py tests/test_notify.py
git commit -m "feat: add threshold/cooldown notification pipeline with telegram send"
```

**Outcome:** `src/equity_scout/notify.py` implemented verbatim. Three deviations in `scripts/run_notify.py` / tests, all noted per the task brief:
1. The plan's `send = None` then `def send(...)` in the `else` branch redefines the same name across branches, which reads as an accidental shadow — restructured into a small `_telegram_sender(config) -> Callable[[int, str], int]` factory; `main()` now does `send = None if config is None else _telegram_sender(config)`. Behavior identical, ruff-clean either way, but the factory form makes the seam's type explicit.
2. The plan's own assertion `pitches[0]["telegram_message_id"] == 501 + pitches[0]["id"] - 1  # 500 + pitch_id` is an awkward way of writing `== 500 + pitches[0]["id"]` (the fake sender returns `500 + pitch_id`); simplified the assertion to the direct identity, fake unchanged.
3. Added the main()-level CLI tests per the Step-3 instruction, mirroring `test_run_radar.py`'s pattern: seed a watchlist via `radar_storage.save_watchlist` (built from real `Watchlist`/`WatchlistEntry`/`SignalReading` dataclasses so the round trip through `load_latest_watchlist`'s JSON layer is exercised), `monkeypatch.delenv` both `COPILOT_TG_*` vars for a guaranteed-clean env, assert exit 0 + "Telegram not configured" + "Pitches created: 1." + the persisted pitch row (`telegram_message_id is None`), plus a fresh-db exit-1 path (`load_latest_watchlist` self-inits per Phase 1, so this exercises the real no-watchlist-yet branch, not an init bug). Caught a real network leak while writing these: `build_pitch`'s default `ask` seam calls the local Ollama server, which isn't running in the sandbox — the first version of the inbox-only CLI test took ~25s per `httpx`'s connect/read retry behavior instead of failing fast. Fixed by monkeypatching `scripts.run_notify.build_pitch` to a fake in that test (same idiom as `test_run_radar.py` monkeypatching `fetch_entry_history`), confirmed back down to <0.1s.

Gate: 265 passed (258 baseline + 7), ruff clean. Commit `8e37d8f`.

**Review fix** (one commit, also covers the Task 3 items above): (a) **resilient batch** — `notify_watchlist` no longer aborts the candidate loop on the first `TelegramError`; the failed send is warned to stderr (`Warnung: Telegram-Versand für {ticker} fehlgeschlagen: {err}`) and the loop CONTINUES, the row keeping `telegram_message_id` NULL. Module docstring now defines NULL message_id as "no sender configured OR send failed — next run re-qualifies the ticker after cooldown". TDD'd via `test_notify_watchlist_continues_after_telegram_error` (first candidate's send raises, second still gets row + message_id, warning captured via capsys) — this was the only failing-first test since only this item changes behavior. (b) **cooldown boundary pinned** — `test_select_candidates_repitches_exactly_at_cooldown_boundary`: last pitch EXACTLY cooldown_days ago → re-pitch allowed (strict `<` is intended; the boundary day is free again). (c) **--dry-run pinned** — `test_main_dry_run_never_sends_even_with_telegram_config`: full COPILOT_TG_* env via `monkeypatch.setenv` + `--dry-run` → exit 0, inbox-only message, row with NULL message_id, and `scripts.run_notify.send_message` monkeypatched to a fail-loudly stub proving it is never called. (d) **zone mapping pinned** — orchestration test asserts `zone_low == 95.0` / `zone_high == 105.0` field-by-field so a swap in notify's `create_pitch` call fails the suite. Gate after review fix: 268 passed (265 + 3 new tests), ruff clean. Known flaky noise, pre-existing and out of scope: the repo-wide `with sqlite3.connect(...)` idiom commits but never closes, so some full-suite runs surface GC-timed `ResourceWarning: unclosed database` (attributed to whichever test runs when GC fires, e.g. test_research); 1-warning and 14-warning runs occur on the identical tree.

---

### Task 5: Decision receiver (`scripts/run_receiver.py`)

**Files:**
- Create: `scripts/run_receiver.py`
- Test: `tests/test_run_receiver.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Receiver loop: canned updates -> inbox decisions + telegram acks (all fakes)."""
from __future__ import annotations

from equity_scout.inbox_storage import create_pitch, load_pitches, set_message_id
from scripts.run_receiver import process_round

NOW = "2026-07-05T13:00:00+00:00"


def _seed_pitch(db: str) -> int:
    pitch_id = create_pitch(
        db, ticker="EXE", watchlist_id=1, price=90.0, composite=0.6,
        zone_low=85.0, zone_high=95.0, pitch="Pitch", created_at=NOW,
    )
    set_message_id(db, pitch_id, 777)
    return pitch_id


def _update(update_id: int, data: str, chat_id: int = 42) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {"id": f"cb{update_id}", "from": {"id": chat_id}, "data": data},
    }


def test_process_round_records_decision_and_acks(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _seed_pitch(db)
    acks: list[tuple[str, str]] = []
    edits: list[tuple[int, str]] = []

    offset = process_round(
        db,
        fetch=lambda offset: [_update(10, f"buy:{pitch_id}")],
        chat_id=42,
        offset=None,
        answer=lambda cb_id, text: acks.append((cb_id, text)),
        edit=lambda message_id, text: edits.append((message_id, text)),
        now=NOW,
    )
    assert offset == 11
    pitch = load_pitches(db)[0]
    assert (pitch["status"], pitch["decided_at"]) == ("buy", NOW)
    assert acks == [("cb10", "✅ Kaufen vermerkt")]
    assert edits and edits[0][0] == 777 and "✅ Kaufen" in edits[0][1]


def test_process_round_acks_already_decided_without_overwriting(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _seed_pitch(db)
    acks: list[tuple[str, str]] = []
    process_round(
        db, fetch=lambda o: [_update(10, f"buy:{pitch_id}")], chat_id=42, offset=None,
        answer=lambda cb_id, text: acks.append((cb_id, text)), edit=lambda m, t: None, now=NOW,
    )
    process_round(
        db, fetch=lambda o: [_update(11, f"pass:{pitch_id}")], chat_id=42, offset=None,
        answer=lambda cb_id, text: acks.append((cb_id, text)), edit=lambda m, t: None, now=NOW,
    )
    assert load_pitches(db)[0]["status"] == "buy"  # first decision wins
    assert "bereits entschieden" in acks[1][1]


def test_process_round_ignores_foreign_and_malformed_updates(tmp_path):
    db = str(tmp_path / "inbox.db")
    pitch_id = _seed_pitch(db)
    offset = process_round(
        db,
        fetch=lambda o: [
            _update(20, f"buy:{pitch_id}", chat_id=999),  # wrong sender
            {"update_id": 21},  # malformed
            _update(22, "buy:12345"),  # unknown pitch
        ],
        chat_id=42, offset=None, answer=lambda c, t: None, edit=lambda m, t: None, now=NOW,
    )
    assert offset == 23
    assert load_pitches(db)[0]["status"] == "open"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_run_receiver.py -v` — expected: import error.

- [ ] **Step 3: Write the implementation**

```python
"""Decision receiver: long-polls Telegram for button presses, records them.

Usage:
    python scripts/run_receiver.py [--db equity_scout.db] [--rounds N]

Requires COPILOT_TG_BOT_TOKEN / COPILOT_TG_CHAT_ID. Runs until interrupted
(--rounds limits polling rounds, mainly for supervised runs). Decisions land in
the inbox (source of truth); the original message is edited with the outcome so
the Telegram thread reflects the decision. Duplicate/late presses are answered
politely and never overwrite an existing decision.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.inbox_storage import decide_pitch, load_pitches
from equity_scout.telegram_client import (
    answer_callback,
    edit_message,
    get_updates,
    load_telegram_config,
    poll_updates,
)

_DECISION_LABEL = {"buy": "✅ Kaufen", "pass": "❌ Ablehnen", "later": "⏸ Später"}


def _pitch_by_id(db_path: str, pitch_id: int) -> dict | None:
    return next((p for p in load_pitches(db_path, limit=1000) if p["id"] == pitch_id), None)


def process_round(
    db_path: str,
    *,
    fetch: Callable[[int | None], list[dict]],
    chat_id: int,
    offset: int | None,
    answer: Callable[[str, str], None],
    edit: Callable[[int, str], None],
    now: str,
) -> int | None:
    """One polling round: apply decisions, ack buttons, edit messages."""
    decisions, offset = poll_updates(fetch, offset, chat_id)
    for action, pitch_id, callback_id in decisions:
        label = _DECISION_LABEL[action]
        if decide_pitch(db_path, pitch_id, action, decided_at=now):
            answer(callback_id, f"{label} vermerkt")
            pitch = _pitch_by_id(db_path, pitch_id)
            if pitch and pitch.get("telegram_message_id"):
                edit(
                    pitch["telegram_message_id"],
                    f"{pitch['pitch']}\n\n— Entscheidung: {label} ({now})",
                )
        else:
            answer(callback_id, "Bereits entschieden oder unbekannt — bereits entschieden?")
    return offset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--rounds", type=int, default=None)
    args = parser.parse_args()

    config = load_telegram_config(dict(os.environ))
    if config is None:
        print("Telegram not configured — receiver cannot run.", file=sys.stderr)
        return 1
    token, chat_id = config["token"], config["chat_id"]

    offset: int | None = None
    rounds = 0
    print("Receiver läuft — Strg+C zum Beenden.")
    try:
        while args.rounds is None or rounds < args.rounds:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            offset = process_round(
                args.db,
                fetch=lambda off: get_updates(token, off),
                chat_id=chat_id,
                offset=offset,
                answer=lambda cb, text: answer_callback(token, cb, text),
                edit=lambda mid, text: edit_message(token, chat_id, mid, text),
                now=now,
            )
            rounds += 1
    except KeyboardInterrupt:
        print("Receiver beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Fix the duplicate-press ack text during implementation: use exactly `"Bereits entschieden."` (the test asserts the substring "bereits entschieden" case-insensitively adjust the test to match the final wording — pick ONE wording and align test + code).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_run_receiver.py -v` — expected: all PASS.

- [ ] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add scripts/run_receiver.py tests/test_run_receiver.py
git commit -m "feat: add long-polling decision receiver recording one-tap verdicts"
```

---

### Task 6: Daily e-mail digest (`digest.py` + `scripts/run_digest.py`)

**Files:**
- Create: `src/equity_scout/digest.py`, `scripts/run_digest.py`
- Test: `tests/test_digest.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Digest rendering (pure) + SMTP send behind a fake transport."""
from __future__ import annotations

from equity_scout.digest import build_digest, load_smtp_config, send_digest

PITCHES = [
    {"id": 1, "ticker": "EXE", "status": "open", "composite": 0.59, "price": 90.72,
     "created_at": "2026-07-05T10:00:00+00:00", "decided_at": None},
    {"id": 2, "ticker": "ABC", "status": "buy", "composite": 0.51, "price": 55.0,
     "created_at": "2026-07-04T10:00:00+00:00", "decided_at": "2026-07-05T09:00:00+00:00"},
]


def test_build_digest_lists_open_and_decided():
    text = build_digest(PITCHES, date_label="2026-07-05")
    assert "EXE" in text and "offen" in text.lower()
    assert "ABC" in text and "✅" in text
    assert "Keine Anlageberatung" in text


def test_build_digest_empty_state():
    text = build_digest([], date_label="2026-07-05")
    assert "keine offenen Pitches" in text.lower()


def test_load_smtp_config_fail_safe(capsys):
    assert load_smtp_config({}) is None
    env = {
        "SMTP_HOST": "h", "SMTP_PORT": "465", "SMTP_USER": "u",
        "SMTP_PASSWORD": "p", "DIGEST_TO": "a@b.c",
    }
    cfg = load_smtp_config(env)
    assert cfg == {"host": "h", "port": 465, "user": "u", "password": "p", "to": "a@b.c"}
    bad = dict(env, SMTP_PORT="nope")
    assert load_smtp_config(bad) is None
    assert "SMTP_PORT" in capsys.readouterr().err


def test_send_digest_uses_transport_seam():
    sent: list[dict] = []

    class FakeSMTP:
        def __init__(self, host, port):
            sent.append({"connect": (host, port)})
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def login(self, user, password):
            sent.append({"login": user})
        def send_message(self, msg):
            sent.append({"subject": msg["Subject"], "to": msg["To"]})

    cfg = {"host": "h", "port": 465, "user": "u", "password": "p", "to": "a@b.c"}
    send_digest(cfg, "Betreff", "Text", smtp_factory=FakeSMTP)
    assert {"connect": ("h", 465)} in sent
    assert any("Betreff" == e.get("subject") for e in sent)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_digest.py -v` — expected: import error.

- [ ] **Step 3: Write the implementation**

```python
"""Daily e-mail digest of the decision inbox.

Rendering is pure; sending goes through an injectable smtp_factory (defaults to
smtplib.SMTP_SSL) so tests never open sockets. Config is fail-safe like the
telegram client: missing/malformed env -> None + stderr hint, never a crash.
"""
from __future__ import annotations

import smtplib
import sys
from email.message import EmailMessage

_STATUS_ICON = {"open": "📬 offen", "buy": "✅ gekauft-Entscheidung",
                "pass": "❌ abgelehnt", "later": "⏸ später"}


def load_smtp_config(env: dict) -> dict | None:
    required = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO")
    if any(not env.get(key) for key in required):
        return None
    try:
        port = int(env["SMTP_PORT"])
    except ValueError:
        print("SMTP_PORT is not an integer — digest disabled.", file=sys.stderr)
        return None
    return {
        "host": env["SMTP_HOST"], "port": port, "user": env["SMTP_USER"],
        "password": env["SMTP_PASSWORD"], "to": env["DIGEST_TO"],
    }


def build_digest(pitches: list[dict], *, date_label: str) -> str:
    """German plain-text digest: open pitches first, then recent decisions."""
    lines = [f"Copilot-Digest {date_label}", ""]
    open_pitches = [p for p in pitches if p["status"] == "open"]
    decided = [p for p in pitches if p["status"] != "open"]
    if not open_pitches:
        lines.append("Aktuell keine offenen Pitches.")
    else:
        lines.append(f"Offene Pitches ({len(open_pitches)}):")
        for p in open_pitches:
            lines.append(
                f"  📬 offen — {p['ticker']} · Score {round(p['composite'] * 100)}/100"
                f" · Kurs {p['price']:.2f} · seit {p['created_at'][:10]}"
            )
    if decided:
        lines.append("")
        lines.append("Entschieden:")
        for p in decided:
            icon = _STATUS_ICON.get(p["status"], p["status"])
            lines.append(f"  {icon} — {p['ticker']} · am {(p['decided_at'] or '')[:10]}")
    lines += ["", "Keine Anlageberatung."]
    return "\n".join(lines)


def send_digest(config: dict, subject: str, body: str, smtp_factory=smtplib.SMTP_SSL) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config["user"]
    msg["To"] = config["to"]
    msg.set_content(body)
    with smtp_factory(config["host"], config["port"]) as smtp:
        smtp.login(config["user"], config["password"])
        smtp.send_message(msg)
```

And `scripts/run_digest.py` (thin CLI: load pitches, `build_digest` with today's date label, send if `load_smtp_config` yields config, else print the digest to stdout and exit 0 with a "SMTP not configured" note; `--db` flag; exit 0 in both paths — an unconfigured digest is not an error). Include a `main()` test in `tests/test_digest.py` for the unconfigured path (capsys: digest text printed).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_digest.py -v` — expected: all PASS.

- [ ] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/digest.py scripts/run_digest.py tests/test_digest.py
git commit -m "feat: add daily inbox digest with smtp transport seam"
```

---

### Task 7: Inbox API endpoints

**Files:**
- Modify: `src/equity_scout/api.py`
- Test: `tests/test_api.py` (append; match existing style, incl. how `POST /api/chat` parses its body — mirror that pattern for the decision POST)

- [ ] **Step 1: Write the failing tests** (sketch — adapt fixture style to the file)

```python
def test_inbox_endpoints_list_and_decide(tmp_path):
    db = str(tmp_path / "inbox.db")
    client = TestClient(create_app(db))
    from equity_scout.inbox_storage import create_pitch

    pitch_id = create_pitch(
        db, ticker="EXE", watchlist_id=1, price=90.0, composite=0.6,
        zone_low=85.0, zone_high=95.0, pitch="P", created_at="2026-07-05T10:00:00+00:00",
    )
    listing = client.get("/api/inbox")
    assert listing.status_code == 200
    assert listing.json()["pitches"][0]["ticker"] == "EXE"
    assert "disclaimer" in listing.json()

    ok = client.post(f"/api/inbox/{pitch_id}/decision", json={"action": "buy"})
    assert ok.status_code == 200
    assert client.get("/api/inbox").json()["pitches"][0]["status"] == "buy"

    conflict = client.post(f"/api/inbox/{pitch_id}/decision", json={"action": "pass"})
    assert conflict.status_code == 409
    unknown = client.post("/api/inbox/999/decision", json={"action": "buy"})
    assert unknown.status_code == 409
    invalid = client.post(f"/api/inbox/{pitch_id}/decision", json={"action": "explode"})
    assert invalid.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api.py -v -k inbox` — expected: 404s.

- [ ] **Step 3: Implement the routes** (closures in `create_app`, before the StaticFiles mount; imports top-of-file)

```python
    @app.get("/api/inbox")
    def inbox() -> JSONResponse:
        return JSONResponse({"pitches": load_pitches(db_path), "disclaimer": DISCLAIMER})

    @app.post("/api/inbox/{pitch_id}/decision")
    def inbox_decision(pitch_id: int, payload: DecisionPayload) -> JSONResponse:
        decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not decide_pitch(db_path, pitch_id, payload.action, decided_at=decided_at):
            raise HTTPException(status_code=409, detail="Pitch unbekannt oder bereits entschieden.")
        return JSONResponse({"ok": True, "disclaimer": DISCLAIMER})
```

with a `DecisionPayload` pydantic model (`action: Literal["buy", "pass", "later"]`) — FastAPI then yields the 422 for invalid actions automatically. Match how `POST /api/chat` declares its payload; if it uses a plain dict + manual validation instead of pydantic, follow THAT idiom and return 422 manually.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api.py -v` — expected: all PASS.

- [ ] **Step 5: Gate and commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check .
git add src/equity_scout/api.py tests/test_api.py
git commit -m "feat: expose decision inbox via GET /api/inbox and decision POST"
```

---

### Task 8: `.env.example` + phase gate

- [ ] **Step 1: Document env vars**

Create/extend `.env.example` in the repo root (check whether one exists first) with the seven new variables, commented in English, values blank. Never touch a real `.env`.

- [ ] **Step 2: Full gate**

Run: `.venv/bin/python -m pytest && .venv/bin/ruff check .` — entire suite green (baseline 241 + new), ruff clean.

- [ ] **Step 3: End-to-end dry smoke (no network, no secrets)**

Run: `python scripts/run_notify.py --db equity_scout.db --dry-run` — expected: "Telegram not configured — writing inbox pitches only." + `Pitches created: N.` (N depends on live watchlist/threshold; N=0 is valid if nothing is in zone above threshold — check `/api/inbox` afterwards via TestClient or sqlite). Then `python scripts/run_digest.py --db equity_scout.db` — digest text printed to stdout. Record observed output.

- [ ] **Step 4: Outcome section + log + commit**

Append the outcome section to THIS plan (implemented/deviations/evidence/follow-ups incl. the Needs-Nico list: BotFather token + chat_id, SMTP creds, live send test), append one AUTOPILOT_LOG.md line, commit as `docs: record phase-2 inbox outcome`.

---

## Self-review notes (spec coverage)

- Spec §6 notify-only-above-threshold + cooldown: Task 4 (`select_candidates`, defaults 0.45 / 7 days as CLI flags).
- Spec §6 Telegram pitch + one-tap buttons: Tasks 1, 4, 5 (tap-approve pattern lifted, sender-check security gate kept).
- Spec §6 pitch content (what/why-now/score-breakdown/risks) + LLM guardrail: Task 2 (facts computed, LLM interprets, deterministic fallback).
- Spec §6 dashboard inbox: Tasks 3, 7 (dashboard UI itself is Phase 6; the API is ready).
- Spec §6 e-mail digest: Task 6.
- Spec §4.2 "decisions queue in Telegram until the local receiver polls": Task 5 (offset handling consumes every update; duplicate presses safe).
- Deliberate scope cuts: no notification on Actions yet (Phase 5 wires `run_notify.py` into CI), no expiry job for stale open pitches (revisit in Phase 3 when exits exist), digest has no HTML variant (plain text, YAGNI).
- Placeholder scan: none — all code complete. Wording of the duplicate-press ack is explicitly left to be aligned test↔code in Task 5 (one decision, documented there).
- Type consistency: `ACTIONS` defined once in `telegram_client.py`, imported by `inbox_storage.py`; the send seam `(pitch_id, text) -> message_id` and ask seam `(question, context) -> str` are each defined in exactly one place.
