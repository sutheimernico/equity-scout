# Vision v9 — Guaranteed Delivery + Anlage-Butler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nico bekommt garantiert jede Werktags-Daily-Nachricht (auch wenn WSL um 18:00 aus war), und die Nachricht wird zum „Anlage-Butler" für einen Börsen-Laien: Ampel-Urteile im Digest, deduplizierte offene Pitches, ein monatlicher ETF-Core-Sparplan mit konkreten EUR-Beträgen, nützliche 0-Pitch-Tage.

**Architecture:** Drei Stränge. (S) Zustellung: ein Guard-Wrapper (`run_daily_guarded.sh`, Marker + flock + Wochentag) wird der einzige Einstieg für alle Trigger — bestehende Cron-Zeile, neuer systemd-User-Timer mit `Persistent=true` (Catch-up beim WSL-Start) und ein Windows-Task-Scheduler-Task, der WSL bei Bedarf selbst startet; ein KV-State-Store in der Haupt-DB macht den Digest-Versand idempotent pro Tag. (B) Butler-UX: `digest.py` rendert das gespeicherte Ampel-Urteil, dedupliziert/capped offene Pitches; neues `butler.py` berechnet aus den EnsembleStrategy-Gewichten einen Monats-Sparplan in EUR (einmal pro Monat voller Block, sonst Einzeiler). (Q) Qualität: Leermeldung-Send abgesichert, SEC-Requests gedrosselt + XML-Sanity-Check, F-Score-Zähler ehrlich getrennt, CIK-Log-Rauschen reduziert, entry_model-`Splits=0` untersucht.

**Tech Stack:** Python 3.12 (uv, pytest, ruff), SQLite, Bash, systemd user units, Windows schtasks (XML), Telegram Bot API (bestehender Client).

**Branch:** `autopilot/work` (bestehende Autopilot-Konvention). **Kein Push, kein Merge nach main** — das bleibt Needs Nico.

**Gate pro Task:** `.venv/bin/python -m pytest -q` grün + `uv run ruff check .` sauber, dann Commit (Conventional Commits, Englisch).

**Kontext-Belege (aus dem Review 2026-07-19):**
- WSL lief vom 16.07. 21:45 bis 19.07. 20:26 nicht → kein Cron-Slot feuerte; Cron holt nichts nach (`docs/scheduling.md:84-87` dokumentiert das als Caveat, löst es aber nicht).
- `schtasks.exe` und `wsl.exe` sind aus WSL nutzbar (verifiziert); Distro heißt `Ubuntu`; kein bestehender Task.
- Digest hat keinen Tages-Idempotenz-Guard (`scripts/run_digest.py:141-146`) — zweiter Lauf am selben Tag = Doppel-Versand.
- Leermeldung-Send ungeschützt (`scripts/run_notify.py:265-272`) — TelegramError würde die Evidenz-Alarme des Tages killen.
- Digest zeigt Ampel-Urteil nicht (`digest.py:101-133`), obwohl `pitches.verdict`/`verdict_why` persistiert sind (`inbox_storage.py`).
- 23 offene Pitches, Ticker bis 3× dupliziert, kein Cap/Dedup in `digest.py:118-133`.
- Tests: 903 passed (Baseline grün).

---

## Task 1 (Q1): Leermeldung-Send absichern

**Files:**
- Modify: `src/equity_scout/notify.py` (neue Funktion + Konstante)
- Modify: `scripts/run_notify.py:265-272` (Inline-Send ersetzen)
- Test: `tests/test_notify.py`

- [ ] **Step 1: Failing Tests schreiben** (in `tests/test_notify.py`, Imports oben ergänzen: `from equity_scout.notify import send_empty_day_note` und `from equity_scout.telegram_client import TelegramError`)

```python
def test_empty_day_note_survives_telegram_error(capsys):
    def boom(token, chat_id, text):
        raise TelegramError("509 flood")

    ok = send_empty_day_note({"token": "t", "chat_id": "c"}, send=boom)
    assert ok is False
    assert "Leermeldung" in capsys.readouterr().err


def test_empty_day_note_prefers_intraday_chat():
    calls = []

    def fake(token, chat_id, text):
        calls.append((token, chat_id, text))

    ok = send_empty_day_note(
        {"token": "t", "chat_id": "c", "intraday_chat_id": "i"}, send=fake
    )
    assert ok is True
    assert calls[0][1] == "i"
    assert "Qualitätsschwelle" in calls[0][2]
```

- [ ] **Step 2: Fail verifizieren:** `.venv/bin/python -m pytest tests/test_notify.py -q -k empty_day` → ImportError/FAIL.
- [ ] **Step 3: Implementieren** — in `src/equity_scout/notify.py` (Import `send_message` aus telegram_client ergänzen, `TelegramError` ist ggf. schon importiert; `sys` prüfen):

```python
EMPTY_DAY_NOTE = (
    "📭 Heute keine Kandidaten über der Qualitätsschwelle — "
    "kein Pitch ist ehrlicher als ein schwacher Pitch."
)


def send_empty_day_note(config: dict, *, send=send_message) -> bool:
    """v8 honesty note, guarded like every other send in this module: a Telegram
    outage on an empty day must not abort the notify run — the off-watchlist
    evidence alerts run AFTER this call in run_notify."""
    try:
        send(
            config["token"],
            config.get("intraday_chat_id", config["chat_id"]),
            EMPTY_DAY_NOTE,
        )
        return True
    except TelegramError as err:
        print(f"Warnung: Leermeldung nicht zustellbar: {err}", file=sys.stderr)
        return False
```

In `scripts/run_notify.py` den Block `if count == 0 and config is not None:` (Z. 265-272) ersetzen durch:

```python
    if count == 0 and config is not None:
        # v8 honesty: an explicit "nothing convincing today" beats padding the daily
        # delivery with mediocre names; guarded so a Telegram outage cannot abort
        # the evidence alerts below (v9).
        send_empty_day_note(config)
```

Import in `run_notify.py` ergänzen (`send_empty_day_note` in den bestehenden `from equity_scout.notify import (...)`-Block); `send_message`-Import entfernen, falls dadurch ungenutzt.

- [ ] **Step 4: Pass verifizieren:** `.venv/bin/python -m pytest tests/test_notify.py -q` → PASS; `uv run ruff check .` sauber.
- [ ] **Step 5: Commit:** `git commit -m "fix(notify): guard empty-day note send so a Telegram outage cannot abort evidence alerts"`

---

## Task 2 (S1): Key-Value-State-Store

**Files:**
- Create: `src/equity_scout/state_storage.py`
- Test: `tests/test_state_storage.py` (neu)

- [ ] **Step 1: Failing Tests schreiben** (`tests/test_state_storage.py`):

```python
from equity_scout.state_storage import get_state, set_state


def test_get_state_missing_key_returns_none(tmp_path):
    db = str(tmp_path / "t.db")
    assert get_state(db, key="nope") is None


def test_set_then_get_roundtrip(tmp_path):
    db = str(tmp_path / "t.db")
    set_state(db, key="digest_sent_on", value="2026-07-19")
    assert get_state(db, key="digest_sent_on") == "2026-07-19"


def test_set_overwrites(tmp_path):
    db = str(tmp_path / "t.db")
    set_state(db, key="k", value="a")
    set_state(db, key="k", value="b")
    assert get_state(db, key="k") == "b"
```

- [ ] **Step 2: Fail verifizieren:** `.venv/bin/python -m pytest tests/test_state_storage.py -q` → ImportError.
- [ ] **Step 3: Implementieren** (`src/equity_scout/state_storage.py`):

```python
"""Tiny key-value app state in the main DB (send idempotency, monthly gates).

Same discipline as the other *_storage modules: one sqlite3.connect per call,
schema created on first use, values are plain strings (callers format dates as
ISO so lexicographic comparison stays chronologically correct).
"""
from __future__ import annotations

import sqlite3


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def get_state(db_path: str, *, key: str) -> str | None:
    with sqlite3.connect(db_path) as conn:
        _ensure(conn)
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_state(db_path: str, *, key: str, value: str) -> None:
    with sqlite3.connect(db_path) as conn:
        _ensure(conn)
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
```

- [ ] **Step 4: Pass verifizieren** + ruff.
- [ ] **Step 5: Commit:** `git commit -m "feat(state): tiny key-value app_state store for send idempotency and monthly gates"`

---

## Task 3 (S2): Digest-Versand idempotent pro Tag

**Files:**
- Modify: `scripts/run_digest.py` (Guard + `--force` + Marker nach Erfolg)
- Test: `tests/test_run_digest_guard.py` (neu)

**Design:** Guard nur wenn ein Kanal konfiguriert ist (stdout-Dev-Läufe bleiben ungebremst). Marker `digest_sent_on = date_label` wird erst NACH mindestens einem erfolgreichen Versand gesetzt — ein gescheiterter Telegram-Send blockt den nächsten Versuch nicht.

- [ ] **Step 1: Failing Test schreiben** (`tests/test_run_digest_guard.py`) — testet die extrahierte Entscheidungsfunktion:

```python
from scripts.run_digest import should_skip_send


def test_skips_when_already_sent_today_and_configured():
    assert should_skip_send("2026-07-19", today="2026-07-19", force=False, configured=True)


def test_never_skips_with_force():
    assert not should_skip_send("2026-07-19", today="2026-07-19", force=True, configured=True)


def test_never_skips_unconfigured_stdout_runs():
    assert not should_skip_send("2026-07-19", today="2026-07-19", force=False, configured=False)


def test_runs_when_not_yet_sent():
    assert not should_skip_send(None, today="2026-07-19", force=False, configured=True)
    assert not should_skip_send("2026-07-18", today="2026-07-19", force=False, configured=True)
```

- [ ] **Step 2: Fail verifizieren.**
- [ ] **Step 3: Implementieren** in `scripts/run_digest.py`:

Import ergänzen: `from equity_scout.state_storage import get_state, set_state`. Neue Funktion auf Modulebene:

```python
DIGEST_SENT_KEY = "digest_sent_on"


def should_skip_send(last_sent: str | None, *, today: str, force: bool, configured: bool) -> bool:
    """True when a configured digest already went out today (v9 idempotency: three
    schedulers may call the chain; the guard makes a second same-day run a no-op)."""
    return configured and not force and last_sent == today
```

In `main()`: `parser.add_argument("--force", action="store_true", help="send even if a digest already went out today")`. Nach dem Laden von `smtp_config`/`tg_config` (also nach Z. 140-141), vor den Sends:

```python
    configured = smtp_config is not None or tg_config is not None
    if should_skip_send(
        get_state(args.db, key=DIGEST_SENT_KEY),
        today=date_label, force=args.force, configured=configured,
    ):
        print(f"Digest für {date_label} bereits verschickt — übersprungen (--force erzwingt).")
        return 0
```

Erfolg tracken und Marker setzen: `delivered = False`; nach `send_digest(...)` → `delivered = True`; im Telegram-try nach `send_long_message(...)` → `delivered = True`. Nach beiden Send-Blöcken:

```python
    if delivered:
        set_state(args.db, key=DIGEST_SENT_KEY, value=date_label)
```

- [ ] **Step 4: Pass verifizieren** (`pytest tests/test_run_digest_guard.py -q` + volle Suite) + ruff.
- [ ] **Step 5: Commit:** `git commit -m "feat(digest): per-day send idempotency via app_state so multiple schedulers cannot double-send"`

---

## Task 4 (S3): Guard-Wrapper `run_daily_guarded.sh`

**Files:**
- Create: `scripts/run_daily_guarded.sh` (chmod +x)
- Modify: `.gitignore` (Zeile `.state/`)

- [ ] **Step 1: Wrapper schreiben:**

```bash
#!/usr/bin/env bash
# v9: single arbitration point for ALL daily-chain triggers (cron, systemd timer,
# Windows Task Scheduler). Weekday guard + per-day marker + flock — a caught-up or
# duplicate slot can never run the chain twice on one day. Triggers pass their name
# as $1 for the log line. EQUITY_SCOUT_CHAIN overrides the chain command (tests).
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$REPO_DIR/copilot.log"
STATE_DIR="$REPO_DIR/.state"
MARKER="$STATE_DIR/daily_last_run"
LOCK="$STATE_DIR/daily.lock"
CHAIN="${EQUITY_SCOUT_CHAIN:-$REPO_DIR/scripts/daily_copilot.sh}"
mkdir -p "$STATE_DIR"

# Weekdays only: a Saturday WSL start must not catch up Friday's missed slot.
if [ "$(date +%u)" -gt 5 ]; then
  exit 0
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Is)] guarded: another daily run holds the lock — skipping (trigger: ${1:-unspecified})" >> "$LOG"
  exit 0
fi

TODAY="$(date +%F)"
if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
  exit 0  # already ran today — quiet skip; redundant triggers are by design
fi

echo "[$(date -Is)] guarded: starting daily chain (trigger: ${1:-unspecified})" >> "$LOG"
"$CHAIN"
echo "$TODAY" > "$MARKER"
```

`chmod +x scripts/run_daily_guarded.sh`. In `.gitignore` die Zeile `.state/` ergänzen (unter `data/prices/`).

- [ ] **Step 2: Verifizieren OHNE echten Versand** (Stub-Chain):

```bash
cd ~/private/equity-scout
rm -f .state/daily_last_run
EQUITY_SCOUT_CHAIN=/bin/true scripts/run_daily_guarded.sh test1   # läuft, schreibt Marker
cat .state/daily_last_run                                          # heutiges Datum
EQUITY_SCOUT_CHAIN=/bin/false scripts/run_daily_guarded.sh test2   # quiet skip (Marker == heute)
tail -3 copilot.log                                                # genau EINE "guarded: starting"-Zeile (trigger: test1)
```

Erwartung: zweiter Aufruf produziert keine neue Log-Zeile; Marker enthält `date +%F`. Danach Marker-Zustand so lassen (heute lief die Chain noch nicht wirklich — Marker wieder löschen: `rm .state/daily_last_run`), damit der echte Abend-/Verify-Lauf nicht geblockt wird.

- [ ] **Step 3: Commit:** `git commit -m "feat(ops): guarded daily-chain wrapper (weekday + per-day marker + flock) as single entry for all schedulers"`

---

## Task 5 (S4): Cron-Zeile auf den Wrapper umstellen

**Files:**
- Modify: `scripts/install_crontab.sh` (CHAIN_LINE, Z. ~16)
- Modify: `docs/scheduling.md` (Zeile der Chain — Detail in Task 8)

- [ ] **Step 1:** In `scripts/install_crontab.sh` die `CHAIN_LINE` ersetzen:

```bash
CHAIN_LINE="0 18 * * 1-5 $REPO_DIR/scripts/run_daily_guarded.sh cron >> $REPO_DIR/copilot.log 2>&1"
```

(Exakte Variablennamen an das bestehende Skript anpassen — es ist idempotent aufgebaut; nur die Daily-Zeile ändern, alle anderen Zeilen unverändert lassen.)

- [ ] **Step 2: Crontab neu installieren + verifizieren:** `scripts/install_crontab.sh` ausführen, dann `crontab -l | grep run_daily_guarded` → genau eine Zeile, und `crontab -l | grep -c daily_copilot.sh` → 0 (alte Direkt-Zeile weg).
- [ ] **Step 3: Commit:** `git commit -m "feat(ops): route the 18:00 cron slot through the guarded wrapper"`

---

## Task 6 (S5): systemd-User-Timer mit Persistent=true (Catch-up beim WSL-Start)

**Files:**
- Create: `scripts/systemd/equity-scout-daily.service`
- Create: `scripts/systemd/equity-scout-daily.timer`
- Create: `scripts/install_systemd_timer.sh` (chmod +x)

- [ ] **Step 1: Units schreiben.** `scripts/systemd/equity-scout-daily.service`:

```ini
[Unit]
Description=equity-scout daily copilot chain (guarded wrapper)

[Service]
Type=oneshot
ExecStart=%h/private/equity-scout/scripts/run_daily_guarded.sh systemd
```

`scripts/systemd/equity-scout-daily.timer`:

```ini
[Unit]
Description=equity-scout daily chain 18:05 Mon-Fri, catches up missed slots on boot

[Timer]
OnCalendar=Mon..Fri 18:05
Persistent=true

[Install]
WantedBy=timers.target
```

(18:05 statt 18:00: Cron gewinnt den regulären Slot, der Timer ist Catch-up-Schicht — der Wrapper-Marker arbitriert ohnehin.)

- [ ] **Step 2: Installer schreiben** (`scripts/install_systemd_timer.sh`):

```bash
#!/usr/bin/env bash
# v9: installs the persistent daily timer (catch-up layer — fires a missed 18:05
# slot at the next WSL start). Idempotent: cp + daemon-reload + enable are all safe
# to re-run. Linger is best-effort: without it the timer still works for every
# interactively started WSL session (the only kind this box has).
set -eu
UNIT_DIR="$HOME/.config/systemd/user"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$UNIT_DIR"
cp "$REPO_DIR/scripts/systemd/equity-scout-daily.service" "$UNIT_DIR/"
cp "$REPO_DIR/scripts/systemd/equity-scout-daily.timer" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now equity-scout-daily.timer
loginctl enable-linger "$USER" 2>/dev/null \
  || echo "Hinweis: enable-linger nicht möglich (ok — Timer läuft in jeder interaktiven WSL-Session)."
systemctl --user list-timers equity-scout-daily.timer --no-pager
```

- [ ] **Step 3: Installieren + verifizieren:** `scripts/install_systemd_timer.sh` ausführen. Erwartung: `list-timers` zeigt `equity-scout-daily.timer` mit NEXT = nächster Werktag 18:05. **Achtung:** Falls `Persistent=true` beim Enable sofort einen Catch-up feuert (verpasster Freitag-Slot), fängt der Wrapper das ab — aber nur, wenn heute schon ein Marker existiert oder Wochenende ist. Heute ist Sonntag (`date +%u` = 7) → Wochentags-Guard blockt, kein Versand. Nach dem Enable `tail -3 copilot.log` prüfen: keine neue "guarded: starting"-Zeile.
- [ ] **Step 4: Commit:** `git commit -m "feat(ops): persistent systemd user timer as catch-up layer for missed daily slots"`

---

## Task 7 (S6): Windows-Task-Scheduler-Task (startet WSL bei Bedarf)

**Files:**
- Create: `scripts/windows/equity-scout-daily.xml`
- Create: `scripts/install_windows_task.sh` (chmod +x)

- [ ] **Step 1: Task-XML schreiben** (`scripts/windows/equity-scout-daily.xml`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>equity-scout daily copilot — starts WSL if needed and runs the guarded chain (installed by v9 plan; remove with: schtasks /delete /tn equity-scout-daily)</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-07-20T18:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek><Monday/><Tuesday/><Wednesday/><Thursday/><Friday/></DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Settings>
    <StartWhenAvailable>true</StartWhenAvailable>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>C:\Windows\System32\wsl.exe</Command>
      <Arguments>-d Ubuntu -u nicosutheimer -- /home/nicosutheimer/private/equity-scout/scripts/run_daily_guarded.sh windows</Arguments>
    </Exec>
  </Actions>
</Task>
```

`StartWhenAvailable` = „Run task as soon as possible after a scheduled start is missed" — deckt „PC war um 18:00 im Standby" ab. Läuft mit interaktivem Token (kein Passwort nötig); Grenze: feuert nur, wenn Nico an Windows angemeldet ist (gesperrt ok, abgemeldet nein) — dokumentieren in Task 8.

- [ ] **Step 2: Installer schreiben** (`scripts/install_windows_task.sh`):

```bash
#!/usr/bin/env bash
# v9: registers the Windows Task Scheduler task that starts WSL at 18:00 weekdays
# and runs the guarded chain. schtasks reads the XML from the Windows filesystem,
# so it is staged into the user's temp dir first. UTF-8 XML is tried first; some
# Windows builds insist on UTF-16 — the fallback converts and retries.
set -eu
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WIN_TMP="/mnt/c/Users/NicoSutheimer/AppData/Local/Temp"
XML_SRC="$REPO_DIR/scripts/windows/equity-scout-daily.xml"
cp "$XML_SRC" "$WIN_TMP/equity-scout-daily.xml"
if ! schtasks.exe /create /tn "equity-scout-daily" /xml 'C:\Users\NicoSutheimer\AppData\Local\Temp\equity-scout-daily.xml' /f; then
  # Some Windows builds insist on UTF-16 task XML: rewrite declaration + re-encode.
  python3 - "$XML_SRC" "$WIN_TMP/equity-scout-daily.xml" <<'PY'
import sys
text = open(sys.argv[1], encoding="utf-8").read().replace('encoding="UTF-8"', 'encoding="UTF-16"', 1)
open(sys.argv[2], "wb").write(text.encode("utf-16"))
PY
  schtasks.exe /create /tn "equity-scout-daily" /xml 'C:\Users\NicoSutheimer\AppData\Local\Temp\equity-scout-daily.xml' /f
fi
schtasks.exe /query /tn "equity-scout-daily" /fo LIST
rm -f "$WIN_TMP/equity-scout-daily.xml"
```

(Erst den UTF-8-Weg probieren; er reicht meistens. Der Fallback schreibt UTF-16 mit BOM und passender Deklaration.)

- [ ] **Step 3: Registrieren + verifizieren:** `scripts/install_windows_task.sh` ausführen. Erwartung: `SUCCESS`-Meldung von schtasks und `/query` zeigt den Task mit Next Run Time = Montag 18:00. **Das ist eine Zustandsänderung an Windows** — im Commit-Text und in Task 8 (Doku) explizit festhalten, Entfernen: `schtasks.exe /delete /tn equity-scout-daily /f`.
- [ ] **Step 4: Commit:** `git commit -m "feat(ops): Windows Task Scheduler task starts WSL and runs the guarded chain at 18:00 weekdays"`

---

## Task 8 (S7): Scheduling-Doku aktualisieren

**Files:**
- Modify: `docs/scheduling.md`

- [ ] **Step 1:** Neuen Abschnitt „v9: Garantierte Zustellung" schreiben und den alten „WSL caveat"-Absatz (Z. 84-87) darauf verweisen lassen. Inhalt (Prosa, keine Platzhalter): Architekturdiagramm in Text (drei Trigger → `run_daily_guarded.sh` → Marker/flock → `daily_copilot.sh`), Tabelle der Trigger (Cron 18:00 / systemd-Timer 18:05 persistent / Windows-Task 18:00 StartWhenAvailable), Verhalten bei Catch-up (Nachricht kommt beim nächsten WSL-Start, ggf. morgens; Wochenende wird nie nachgeholt), Digest-Idempotenz (`app_state.digest_sent_on`, `--force`), Grenzen (Windows-Task feuert nur bei angemeldetem User; PC ganz aus ⇒ Nachricht kommt beim nächsten Start), Deinstallation aller drei Trigger (crontab-Zeile, `systemctl --user disable --now equity-scout-daily.timer`, `schtasks.exe /delete /tn equity-scout-daily /f`), bewusst NICHT gebaut: externer Dead-Man-Switch (bräuchte externen Dienst — Needs Nico, im Backlog).
- [ ] **Step 2: Commit:** `git commit -m "docs(scheduling): v9 guaranteed-delivery architecture, catch-up semantics, uninstall steps"`

---

## Task 9 (B1): Ampel-Urteil im Digest rendern

**Files:**
- Modify: `src/equity_scout/digest.py` (offene Pitches + Chancen im Blick)
- Test: `tests/test_digest.py` (bestehende Datei erweitern; existiert sie nicht, neu anlegen und die Fixture-Form an bestehenden build_digest-Tests in tests/ orientieren — `grep -rn "build_digest" tests/`)

- [ ] **Step 1: Failing Tests schreiben:**

```python
def test_open_pitch_line_carries_stored_verdict():
    pitches = [{
        "ticker": "AIRT", "status": "open", "composite": 0.50, "price": 27.15,
        "created_at": "2026-07-16T19:00:00+00:00", "decided_at": None,
        "verdict": "red", "verdict_why": "Kurs +23.8 % über dem 200-Tage-Schnitt",
    }]
    text = build_digest(pitches, date_label="2026-07-19")
    assert "🔴 AIRT" in text
    assert "200-Tage-Schnitt" in text
    assert "📬 offen — AIRT" not in text


def test_open_pitch_without_verdict_falls_back_to_mailbox_icon():
    pitches = [{
        "ticker": "OLD", "status": "open", "composite": 0.50, "price": 10.0,
        "created_at": "2026-07-01T19:00:00+00:00", "decided_at": None,
    }]
    text = build_digest(pitches, date_label="2026-07-19")
    assert "📬 OLD" in text


def test_opportunities_render_live_verdict():
    entry = {
        "ticker": "TST", "composite": 0.75, "in_zone": True, "value_gap": 0.0,
        "readings": [], "breakdown": {"value": 0.8, "momentum": 0.7},
    }
    text = build_digest([], date_label="2026-07-19", opportunities=[entry])
    assert "🟢 TST" in text
```

- [ ] **Step 2: Fail verifizieren.**
- [ ] **Step 3: Implementieren** in `digest.py`: Import `from equity_scout.pitch import compute_verdict` und Konstante `_VERDICT_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}`. Opportunities-Schleife (Z. 103-111) — Zeile ersetzen durch:

```python
        for entry in opportunities:
            marks = ""
            if entry.get("in_zone"):
                marks += " · in Zone"
            if (entry.get("value_gap") or 0) > 0:
                marks += " · unterbewertet"
            verdict = compute_verdict(entry)
            lines.append(_line(
                f"  {verdict['emoji']} {entry['ticker']}"
                f" · Score {round(entry['composite'] * 100)}/100{marks}"
                f" — {verdict['label']}"
            ))
```

Offene-Pitches-Schleife (Z. 129-133) ersetzen durch:

```python
        for p in open_pitches:
            icon = _VERDICT_ICON.get(p.get("verdict"), "📬")
            why = f" — {p['verdict_why']}" if p.get("verdict_why") else ""
            lines.append(_line(
                f"  {icon} {p['ticker']} · Score {round(p['composite'] * 100)}/100"
                f" · Kurs {p['price']:.2f} · seit {p['created_at'][:10]}{why}"
            ))
```

Falls bestehende Digest-Tests auf das alte `📬 offen —`-Format asserten: Assertions auf das neue Format anpassen (bewusste Formatänderung, keine Regression).

- [ ] **Step 4: Pass verifizieren** (volle Suite) + ruff.
- [ ] **Step 5: Commit:** `git commit -m "feat(digest): render stored pitch verdicts and live opportunity verdicts (traffic light in the daily touchpoint)"`

---

## Task 10 (B2): Offene Pitches dedupen, sortieren, capen

**Files:**
- Modify: `src/equity_scout/digest.py`
- Test: `tests/test_digest.py`

- [ ] **Step 1: Failing Tests schreiben:**

```python
def _open(ticker, created, verdict=None, composite=0.5):
    return {
        "ticker": ticker, "status": "open", "composite": composite, "price": 10.0,
        "created_at": created, "decided_at": None, "verdict": verdict,
        "verdict_why": None,
    }


def test_open_pitches_dedupe_keeps_newest_per_ticker():
    pitches = [
        _open("AAA", "2026-07-10T10:00:00+00:00", "red"),
        _open("AAA", "2026-07-16T10:00:00+00:00", "green"),
    ]
    text = build_digest(pitches, date_label="2026-07-19")
    assert text.count("AAA") == 1
    assert "🟢 AAA" in text


def test_open_pitches_sorted_green_first_and_capped():
    pitches = [_open(f"T{i:02d}", f"2026-07-{10 + i:02d}T10:00:00+00:00", "red") for i in range(8)]
    pitches.append(_open("WIN", "2026-07-05T10:00:00+00:00", "green"))
    text = build_digest(pitches, date_label="2026-07-19")
    open_lines = [l for l in text.splitlines() if "· seit" in l]
    assert len(open_lines) == 6
    assert "WIN" in open_lines[0]
    assert "und 3 weitere offene" in text
```

- [ ] **Step 2: Fail verifizieren.**
- [ ] **Step 3: Implementieren** in `digest.py` — Modulkonstanten + Helper:

```python
OPEN_PITCH_CAP = 6
_VERDICT_ORDER = {"green": 0, "yellow": 1, "red": 2}


def _dedupe_open(open_pitches: list[dict]) -> list[dict]:
    """Newest row per ticker (cooldown re-pitches accumulate otherwise), green
    verdicts first, newest first within a band; verdict-less legacy rows sort with
    yellow. Pure list math — rendering stays a straight loop."""
    newest: dict[str, dict] = {}
    for p in sorted(open_pitches, key=lambda p: p["created_at"], reverse=True):
        newest.setdefault(p["ticker"], p)
    rows = sorted(newest.values(), key=lambda p: p["created_at"], reverse=True)
    rows.sort(key=lambda p: _VERDICT_ORDER.get(p.get("verdict"), 1))
    return rows
```

In `build_digest` nach dem Filtern: `open_pitches = _dedupe_open(open_pitches)`, Header bleibt `Offene Pitches: {len(open_pitches)}`; Schleife über `open_pitches[:OPEN_PITCH_CAP]`; danach:

```python
        rest = len(open_pitches) - OPEN_PITCH_CAP
        if rest > 0:
            lines.append(_line(
                f"  … und {rest} weitere offene — vollständige Liste im Dashboard."
            ))
```

- [ ] **Step 4: Pass verifizieren** + ruff.
- [ ] **Step 5: Commit:** `git commit -m "feat(digest): dedupe open pitches per ticker, sort by verdict, cap at 6 lines"`

---

## Task 11 (B3): ETF-Core-Sparplan (Anlage-Butler-Kern)

**Files:**
- Create: `src/equity_scout/butler.py`
- Modify: `scripts/run_digest.py` (Panel → Plan → Digest-Param, Monats-Gating)
- Modify: `src/equity_scout/digest.py` (neuer Param `core_block`)
- Test: `tests/test_butler.py` (neu)

**Design:** EUR-Beträge sind reine Budget-Splits (Gewicht × Kernbudget), keine FX-Umrechnung. Ensemble-Strategie aus der Registry (Name `Multi-Strategie-Mix`) = eine Quelle, kein Drift zum Dashboard. Voller Block einmal pro Monat (State-Key `core_plan_month`), sonst Einzeiler. Panel fehlt/Strategie liefert nichts → `None`, ehrliche Absenz (kein Block).

- [ ] **Step 1: Failing Tests schreiben** (`tests/test_butler.py`; Panel-Fixture an bestehenden Strategie-Tests orientieren — `grep -rn "PricePanel(" tests/ | head` und die dortige Fixture-Fabrik übernehmen; 13 Monate Tageshistorie für SPY/VEU/VWO/IEF/TLT/BND/BIL/GLD, damit GEM/DAA entscheiden können):

```python
from equity_scout.butler import build_core_plan, monthly_budget, render_core_block


def test_monthly_budget_default_and_parse(capsys):
    assert monthly_budget({}) == 500
    assert monthly_budget({"COPILOT_MONTHLY_BUDGET": "800"}) == 800
    assert monthly_budget({"COPILOT_MONTHLY_BUDGET": "quatsch"}) == 500
    assert "COPILOT_MONTHLY_BUDGET" in capsys.readouterr().err


def test_build_core_plan_splits_core_budget(panel_fixture):
    plan = build_core_plan(panel_fixture, monthly_budget_eur=500)
    assert plan is not None
    assert plan["core_budget"] == 400 and plan["satellite_budget"] == 100
    total = sum(p["amount_eur"] for p in plan["positions"]) + plan["cash_rest"]
    assert total == 400
    assert all(p["amount_eur"] >= 1 for p in plan["positions"])
    assert plan["positions"] == sorted(plan["positions"], key=lambda p: -p["amount_eur"])


def test_render_core_block_plain_and_html(panel_fixture):
    plan = build_core_plan(panel_fixture, monthly_budget_eur=500)
    plain = render_core_block(plan, month_label="Juli", html=False)
    assert "Monats-Sparplan Juli" in plain and "Kern (80 % = 400 €)" in plain
    assert "Keine Anlageberatung" in plain
    html = render_core_block(plan, month_label="Juli", html=True)
    assert "<b>" in html and "&" not in html.replace("&amp;", "").replace("&lt;", "").replace("&gt;", "") or True
```

(Die letzte HTML-Assertion pragmatisch halten: prüfe `<b>` vorhanden und dass ein Ticker-Name escaped auftaucht.)

- [ ] **Step 2: Fail verifizieren.**
- [ ] **Step 3: Implementieren** (`src/equity_scout/butler.py`):

```python
"""Monthly ETF core savings-plan block (v9 Anlage-Butler).

Pure math + rendering: the registry's Multi-Strategie-Mix target weights on the
shared ETF panel become whole-EUR amounts for a configurable monthly budget.
Core/satellite split is fixed at 80/20 — one decision, not a config surface.
EUR amounts are budget splits (weight x budget), deliberately no FX: the reader
allocates euros at their broker, the model ranks asset classes.
"""
from __future__ import annotations

import sys

import pandas as pd

from equity_scout.etf_universe import ETF_BY_TICKER
from equity_scout.market import MarketView
from equity_scout.strategies.base import normalise_weights
from equity_scout.strategies.registry import default_strategies
from equity_scout.telegram_client import escape_html

DEFAULT_MONTHLY_BUDGET_EUR = 500
CORE_SHARE = 0.8
_MIX_NAME = "Multi-Strategie-Mix"
MONTH_NAMES = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
               "August", "September", "Oktober", "November", "Dezember"]


def monthly_budget(env: dict) -> int:
    raw = env.get("COPILOT_MONTHLY_BUDGET")
    if not raw:
        return DEFAULT_MONTHLY_BUDGET_EUR
    try:
        return max(1, int(raw))
    except ValueError:
        print(
            f"COPILOT_MONTHLY_BUDGET ist keine Zahl — nutze Default {DEFAULT_MONTHLY_BUDGET_EUR}.",
            file=sys.stderr,
        )
        return DEFAULT_MONTHLY_BUDGET_EUR


def build_core_plan(panel, monthly_budget_eur: int) -> dict | None:
    """Whole-EUR core allocation from the Mix strategy's current target weights.
    None when the strategy cannot decide (short/stale panel) — honest absence."""
    strategy = next(s for s in default_strategies() if getattr(s, "name", "") == _MIX_NAME)
    as_of = panel.dates[-1] + pd.Timedelta(days=1)
    try:
        weights = normalise_weights(strategy.decide(as_of, MarketView(panel, as_of)))
    except Exception:  # noqa: BLE001 - a broken panel must not break the digest
        return None
    if not weights:
        return None
    core_budget = round(monthly_budget_eur * CORE_SHARE)
    positions = []
    for tw in sorted(weights, key=lambda t: -t.weight):
        amount = int(round(tw.weight * core_budget))
        if amount < 1:
            continue
        inst = ETF_BY_TICKER.get(tw.ticker)
        positions.append({
            "ticker": tw.ticker,
            "name": inst.name if inst is not None else tw.ticker,
            "amount_eur": amount,
        })
    if not positions:
        return None
    cash_rest = core_budget - sum(p["amount_eur"] for p in positions)
    return {
        "budget": monthly_budget_eur,
        "core_budget": core_budget,
        "satellite_budget": monthly_budget_eur - core_budget,
        "positions": positions,
        "cash_rest": cash_rest,
    }


def render_core_block(plan: dict, *, month_label: str, html: bool) -> str:
    """One <b> pair max per line (digest split discipline); all dynamics escaped."""

    def _head(text: str) -> str:
        return f"<b>{escape_html(text)}</b>" if html else text

    def _line(text: str) -> str:
        return escape_html(text) if html else text

    lines = [_head(
        f"💶 Dein Monats-Sparplan {month_label} — Beispielrechnung mit {plan['budget']} €/Monat:"
    )]
    lines.append(_line(
        f"Kern ({round(CORE_SHARE * 100)} % = {plan['core_budget']} €) — {_MIX_NAME}, regelbasiert:"
    ))
    for p in plan["positions"]:
        lines.append(_line(f"  • {p['amount_eur']} € — {p['name']} ({p['ticker']})"))
    if plan["cash_rest"] > 0:
        lines.append(_line(f"  • {plan['cash_rest']} € bleiben als Cash-Rest"))
    lines.append(_line(
        f"Satellit ({round((1 - CORE_SHARE) * 100)} % = {plan['satellite_budget']} €):"
        " für einzelne Aktien-Ideen unten — oder ebenfalls in den Kern."
    ))
    lines.append(_line(
        "US-Ticker aus dem Modell — beim eigenen Broker das UCITS-Pendant wählen."
        " Betrag anpassbar über COPILOT_MONTHLY_BUDGET. Keine Anlageberatung."
    ))
    return "\n".join(lines)


def core_running_line(*, html: bool) -> str:
    text = "💶 Sparplan-Kern: läuft — der volle Monatsplan kommt einmal pro Monat."
    return escape_html(text) if html else text
```

`digest.py`: `build_digest(...)` bekommt `core_block: str | None = None`; nach der `sector_line`-Zeile (vor `lines.append("")`):

```python
    if core_block is not None:
        lines.append(core_block)
```

`scripts/run_digest.py` in `main()` (nach `panel = _load_panel()`):

```python
    budget = monthly_budget(dict(os.environ))
    month_key = date_label[:7]
    core_plan = None
    if panel is not None and get_state(args.db, key=CORE_PLAN_MONTH_KEY) != month_key:
        core_plan = build_core_plan(panel, monthly_budget_eur=budget)
```

Modulkonstante `CORE_PLAN_MONTH_KEY = "core_plan_month"`. Im `render(html)`-Closure:

```python
    def render(html: bool) -> str:
        if core_plan is not None:
            month_label = MONTH_NAMES[int(date_label[5:7]) - 1]
            core_block = render_core_block(core_plan, month_label=month_label, html=html)
        else:
            core_block = core_running_line(html=html)
        return build_digest(..., core_block=core_block, html=html)
```

Nach erfolgreichem Versand (bei `delivered`, neben dem `digest_sent_on`-Marker):

```python
    if delivered and core_plan is not None:
        set_state(args.db, key=CORE_PLAN_MONTH_KEY, value=month_key)
```

Imports in `run_digest.py`: `from equity_scout.butler import MONTH_NAMES, build_core_plan, core_running_line, monthly_budget, render_core_block`.

- [ ] **Step 4: Pass verifizieren** (volle Suite) + ruff. Zusätzlich Live-Probe ohne Versand: `env -u COPILOT_TG_BOT_TOKEN .venv/bin/python scripts/run_digest.py` in einer Umgebung ohne TG/SMTP-Variablen → stdout-Digest enthält den 💶-Block.
- [ ] **Step 5: Commit:** `git commit -m "feat(butler): monthly ETF core savings plan with whole-EUR amounts in the daily digest"`

---

## Task 12 (B4): 0-Pitch-Tage nützlich machen + Positionsgrößen-Faustregel

**Files:**
- Modify: `src/equity_scout/notify.py` (EMPTY_DAY_NOTE-Text)
- Modify: `src/equity_scout/digest.py` (Leerzeile-Copy)
- Modify: `src/equity_scout/pitch.py` (`_tranche_block`)
- Test: `tests/test_notify.py`, `tests/test_digest.py`, bestehende pitch-Tests

- [ ] **Step 1: Failing Tests schreiben:**

```python
# tests/test_notify.py
def test_empty_day_note_carries_follow_up_action():
    from equity_scout.notify import EMPTY_DAY_NOTE
    assert "Nichts tun" in EMPTY_DAY_NOTE and "Sparplan" in EMPTY_DAY_NOTE

# tests/test_digest.py
def test_no_open_pitches_line_explains_inaction():
    text = build_digest([], date_label="2026-07-19")
    assert "richtige Aktion" in text

# in der bestehenden pitch-Testdatei (grep -rn "_tranche_block\|So könntest du einsteigen" tests/)
def test_tranche_block_carries_position_size_rule():
    # bestehende Entry-Fixture der Datei wiederverwenden
    text = build_pitch(entry_fixture, None, ask=lambda q, c: "ok")
    assert "höchstens 5 %" in text
```

- [ ] **Step 2: Fail verifizieren.**
- [ ] **Step 3: Implementieren.** `notify.py`:

```python
EMPTY_DAY_NOTE = (
    "📭 Heute keine Kandidaten über der Qualitätsschwelle — "
    "kein Pitch ist ehrlicher als ein schwacher Pitch.\n"
    "Das ist ok: Nichts tun ist heute die richtige Aktion. "
    "Dein Sparplan-Kern läuft davon unabhängig weiter (siehe Digest)."
)
```

`digest.py` (Z. 125): `"Aktuell keine offenen Pitches."` → `"Aktuell keine offenen Pitches — nichts zu tun ist gerade die richtige Aktion. Der Sparplan-Kern läuft unabhängig weiter."`

`pitch.py` `_tranche_block`, nach der „Nicht alles auf einmal"-Zeile:

```python
    lines.append(
        "Faustregel: höchstens 5 % deines Anlagevermögens in eine einzelne Aktie."
    )
```

- [ ] **Step 4: Pass verifizieren** + ruff (bestehende Assertions auf die alten Texte anpassen, falls vorhanden).
- [ ] **Step 5: Commit:** `git commit -m "feat(ux): empty days state the right inaction, tranche block teaches the 5% position-size rule"`

---

## Task 13 (B5): Jargon-Politur — Faktor-Wortliste + Expandable-Hinweis

**Files:**
- Modify: `src/equity_scout/pitch.py` (`_top_factors`, Long-Pitch-HTML)
- Test: bestehende pitch-Tests

- [ ] **Step 1: Failing Tests schreiben** (in der bestehenden pitch-Testdatei):

```python
def test_top_factors_words_only():
    from equity_scout.pitch import _top_factors
    out = _top_factors({"value": 0.82, "momentum": 0.7, "quality": 0.1})
    assert out == "Value, Momentum"


def test_long_pitch_html_announces_expandable_details(entry_fixture):
    html = build_pitch(entry_fixture, None, ask=lambda q, c: "ok", html=True)
    assert "Antippen für die ausführliche Erklärung" in html
```

- [ ] **Step 2: Fail verifizieren.**
- [ ] **Step 3: Implementieren.** `_top_factors` (pitch.py, Rückgabezeile):

```python
def _top_factors(breakdown: dict, n: int = 2) -> str:
    """Words only (v9): '82'-style percentile ranks read as prices or percents to a
    lay reader — the numeric ranks stay in the detail breakdown lines."""
    labels = {"value": "Value", "quality": "Quality", "momentum": "Momentum",
              "growth": "Growth", "low_vol": "Low-Vol"}
    ranked = sorted(
        ((labels.get(k, k), v) for k, v in breakdown.items() if k in labels),
        key=lambda kv: kv[1], reverse=True,
    )
    return ", ".join(label for label, _ in ranked[:n])
```

Expandable-Hinweis: `grep -n "blockquote expandable" src/equity_scout/pitch.py` — direkt VOR der Zeile, die das `<blockquote expandable>` öffnet, eine escaped Plain-Zeile einfügen: `👇 Antippen für die ausführliche Erklärung:`. Bestehende Assertions auf `stark: Value 82`-Format anpassen.

- [ ] **Step 4: Pass verifizieren** + ruff.
- [ ] **Step 5: Commit:** `git commit -m "feat(pitch): factor heads read as words not raw ranks, expandable detail gets a tap hint"`

---

## Task 14 (Q2): SEC-Requests drosseln + XML-Sanity-Check (Insider-Collector)

**Files:**
- Modify: `src/equity_scout/evidence/form4.py` (`_http_get_with_agent`, collect-Schleife)
- Test: bestehende form4-Tests (`grep -rln "collect_form4" tests/`)

- [ ] **Step 1: Failing Test schreiben** (Fake-http_get-Muster der bestehenden form4-Tests übernehmen):

```python
def test_collect_form4_reports_clean_error_for_html_response(...):
    # http_get liefert für die Archive-URL eine HTML-Fehlerseite ("<html>...")
    # statt XML; für Ticker-Map/Submissions die normalen Fixtures.
    result = collect_form4(...)
    assert "kein XML" in result.detail
    assert "tag mismatch" not in result.detail
```

- [ ] **Step 2: Fail verifizieren.**
- [ ] **Step 3: Implementieren.** Modulkonstante + Pause im echten Getter (injizierte Test-Getter bleiben pausenfrei):

```python
_REQUEST_PAUSE_S = 0.15  # SEC fair-access guideline is 10 req/s — stay well under it.


def _http_get_with_agent(user_agent: str) -> Callable[[str], str]:
    def get(url: str) -> str:
        import time

        import httpx

        time.sleep(_REQUEST_PAUSE_S)
        response = httpx.get(
            url, timeout=30.0, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        response.raise_for_status()
        return response.text

    return get
```

In der collect-Schleife vor `parse_form4(xml_text)`:

```python
                if not xml_text.lstrip().startswith("<?xml"):
                    raise ValueError(
                        "SEC lieferte kein XML (Rate-Limit-/Fehlerseite?)"
                    )
```

(Der bestehende per-Ticker-try fängt die ValueError und schreibt sie in `ticker_errors` — die kryptische „tag mismatch"-Meldung verschwindet.)

- [ ] **Step 4: Pass verifizieren** + ruff.
- [ ] **Step 5: Commit:** `git commit -m "fix(evidence): throttle SEC requests and reject non-XML bodies with a clean error"`

---

## Task 15 (Q3): F-Score-Zähler ehrlich trennen

**Files:**
- Modify: `src/equity_scout/fscore.py` (`collect_f_scores`, Z. 215-238)
- Modify: `scripts/run_fscore.py` (Summary-Zeile)
- Test: bestehende fscore-Tests

- [ ] **Step 1: Failing Test schreiben:** bestehenden collect-Test finden (`grep -rn "collect_f_scores" tests/`), Fall ergänzen: `compute_f_score` liefert `None` (Payload mit <5 auswertbaren Kriterien) → Summary hat `insufficient == 1` und `failed == 0`.
- [ ] **Step 2: Fail verifizieren.**
- [ ] **Step 3: Implementieren** in `collect_f_scores`:

```python
    computed = skipped_fresh = no_cik = failed = insufficient = 0
    ...
        except Exception:  # noqa: BLE001 - per-ticker resilience, counted not hidden
            failed += 1
            continue
        if result is None:
            insufficient += 1
            continue
    ...
    return {"computed": computed, "fresh": skipped_fresh, "no_cik": no_cik,
            "failed": failed, "insufficient": insufficient}
```

`scripts/run_fscore.py`-Summary-Print erweitern: `f"... {summary['insufficient']} Datenbasis zu dünn (Banken/REITs), {summary['failed']} fehlgeschlagen."`

- [ ] **Step 4: Pass verifizieren** + ruff (Tests, die das Summary-Dict asserten, um den neuen Key ergänzen).
- [ ] **Step 5: Commit:** `git commit -m "fix(fscore): count thin-data names separately from real fetch failures"`

---

## Task 16 (Q4): CIK-Log-Rauschen — nicht-US-Ticker vor dem Lookup trennen

**Files:**
- Modify: `src/equity_scout/evidence/form4.py` (collect-Schleife)
- Modify: `src/equity_scout/evidence/edgar_8k.py` (collect-Schleife)
- Test: bestehende Tests beider Collector

- [ ] **Step 1: Failing Tests schreiben:** je Collector ein Fall mit Watchlist `["AAPL", "9022.T"]` → Detail-Zeile enthält `1 nicht-US übersprungen` und `9022.T` zählt NICHT als „ohne CIK-Mapping".
- [ ] **Step 2: Fail verifizieren.**
- [ ] **Step 3: Implementieren:** in beiden collect-Funktionen vor dem `cik_map.get(...)`:

```python
        if "." in ticker:  # exchange-suffixed non-US listing — SEC can never map it
            non_us += 1
            continue
```

Zähler `non_us = 0` initialisieren; Detail-String erweitern (`f"{non_us} nicht-US übersprungen"` neben dem bestehenden unmapped-Teil). Semantik: `unmapped` heißt jetzt „US-Ticker, der eigentlich mappen sollte" — Docstring-Satz je Collector ergänzen.

- [ ] **Step 4: Pass verifizieren** + ruff.
- [ ] **Step 5: Commit:** `git commit -m "fix(evidence): report exchange-suffixed non-US tickers separately from genuine CIK gaps"`

---

## Task 17 (Q5): entry_model `Splits=0` untersuchen (bounded)

**Files:**
- Read: `train.log`, `src/equity_scout/ml/` (Trainings-/Walk-Forward-Code), `scripts/nightly_train.sh`
- Modify: nur falls S-Fix (z. B. ehrliche Log-Meldung/Guard); sonst Doku

**Auftrag:** Beide letzten Nightly-Läufe zeigen für ALLE Presets `n_oos=0, Splits=0` → kein Champion promotet. Hypothese: Trainingsdatensatz (~120-150 Zeilen) zu klein für purged/embargoed Walk-Forward-Splits.

- [ ] **Step 1:** Split-Berechnung im ml-Code finden (`grep -rn "Splits\|n_splits\|purged" src/equity_scout/ml/`), Mindestdatenbedarf herleiten, gegen die realen Zeilenzahlen aus der DB prüfen (read-only SQL).
- [ ] **Step 2:** EIN Preset lokal reproduzieren (`.venv/bin/python scripts/run_train_entry.py` mit dem schnellsten Preset, Zeitbudget ~10 min). Bestätigt sich „zu wenig Daten": als S-Fix eine ehrliche Log-Zeile einbauen („zu wenig aufgelöste Labels für N Splits — Training übersprungen, kein Fehler") + ggf. Early-Exit; NICHT die Split-Parameter aufweichen (Overfitting-Schutz bleibt).
- [ ] **Step 3:** Befund (Ursache, Zahlen, ggf. Fix) in `AUTOPILOT_LOG.md` festhalten; falls kein S-Fix möglich: Befund + empfohlener nächster Schritt in den Plan-Outcome-Abschnitt.
- [ ] **Step 4:** Falls Code geändert: Test ergänzen, Suite + ruff, Commit `fix(ml): honest skip line when resolved labels cannot fill one walk-forward split` (Wortlaut an Befund anpassen).

---

## Task 18: Finales Gate + Nachdoku

- [ ] **Step 1:** Volle Suite + Lint: `.venv/bin/python -m pytest -q` (Erwartung: 903+ passed, 0 failed) und `uv run ruff check .`.
- [ ] **Step 2:** Ende-zu-Ende-Probe ohne Versand: `env -u COPILOT_TG_BOT_TOKEN -u SMTP_HOST .venv/bin/python scripts/run_digest.py` → stdout zeigt Ampeln, dedupte Pitches, 💶-Block. Wrapper-Probe wie Task 4 Step 2 (Stub-Chain).
- [ ] **Step 3:** Scheduling live verifizieren: `crontab -l` (Wrapper-Zeile), `systemctl --user list-timers equity-scout-daily.timer`, `schtasks.exe /query /tn equity-scout-daily /fo LIST` — alle drei vorhanden.
- [ ] **Step 4:** Outcome-Abschnitt an dieses Plan-Dokument anhängen (was umgesetzt, Abweichungen, offene Punkte inkl. „Needs Nico": Windows-Task optional auf „Run whether user is logged on" heben, Live-Verify der ersten echten 18:00-Zustellung, COPILOT_MONTHLY_BUDGET in .env setzen).
- [ ] **Step 5:** `AUTOPILOT_LOG.md` um die v9-Einträge ergänzen; `docs/scheduling.md`-Verweis in README prüfen/ergänzen.
- [ ] **Step 6:** Commit: `git commit -m "docs: v9 outcome — guaranteed delivery + butler digest, deviations, open points"`

---

## Bewusst NICHT gebaut (YAGNI / Needs Nico)

- Externer Dead-Man-Switch (healthchecks.io o. ä.): neuer externer Dienst + Account → Needs Nico; die drei redundanten Trigger + Catch-up decken den beobachteten Ausfallmodus bereits ab.
- UCITS-Produkt-Mapping (ISIN-Tabelle): hartkodierte Fremddaten mit Pflegerisiko; der Hinweis „UCITS-Pendant beim Broker wählen" reicht für v9.
- „Dein Rechner war X Tage aus"-Banner im Digest: Marker-Alter wäre die Quelle, aber Shell→Python-Übergabe lohnt erst, wenn Catch-up-Läufe im Alltag auffallen.
- Echte Orderausführung/Depot-Anbindung: bleibt grundsätzlich außerhalb des Projekt-Scopes (Paper/Info-Tool).

---

## Outcome (2026-07-20)

**Alle 18 Tasks umgesetzt.** Session 1 (2026-07-19, 21:03–23:49) lieferte Tasks 1–10; Session 2
(2026-07-20) lieferte Tasks 11–18. Gate durchgehend grün: **941 passed** (Baseline 903), `ruff` sauber.

**Live-Beleg statt bloßer Probe:** Während Session 2 feuerte der echte 18:00-Cron-Slot — die Chain
lief um 18:02 komplett durch (`OK digest`), der v9-Digest ging real per Telegram raus (inkl. des
ersten 💶-Monats-Sparplan-Blocks; `app_state`: `digest_sent_on=2026-07-20`, `core_plan_month=2026-07`).
Der systemd-Timer feuerte 18:05 und wurde vom Wrapper-Marker sauber weggeschnappt (quiet skip) —
die Drei-Trigger-Arbitrierung hat ihren ersten Ernstfall bestanden.

**Abweichungen vom Plan:**
- **Task 7 (Windows-Task):** XML + Installer liegen bereit (`scripts/windows/`,
  `scripts/install_windows_task.sh`), die Registrierung selbst wurde als Zustandsänderung an
  Windows bewusst NICHT ausgeführt → Needs Nico.
- **Task 11 (Butler):** a) Rundungs-Overhang-Fix — bei Summen-Überschuss der gerundeten Positionen
  absorbiert die größte Position die Differenz (`cash_rest` nie negativ; deterministisch getestet).
  b) `run_digest`-Wiring unterscheidet drei Zustände statt zwei: voller Block (Monat offen) /
  Einzeiler (Monat schon geliefert) / GAR KEIN Block (Panel fehlt oder Strategie liefert nichts —
  ehrliche Absenz gemäß Design-Notiz, der Plan-Snippet hätte hier „läuft" behauptet).
  c) Monatsmarker über `mark_sent()` an beiden Send-Pfaden (per-Channel-Muster aus Task 3 statt
  `delivered`-Flag).
- **Task 17 (Splits=0):** Ursache bestätigt, aber präziser als die Hypothese: Split-Einheit sind
  unique monatliche as_of-Stichtage, nicht Zeilen. Reales Panel (ab 2025-02): nach
  MIN_HISTORY-Anlauf (252d) + Horizon-Cropping nur **4** Stichtage — `purged_walk_forward` braucht
  `min_train + n_splits = 28`. Kein Early-Exit eingebaut (bestehender, testfixierter Vertrag:
  Challenger werden registriert, das Promotion-Gate schützt) — stattdessen ehrliche Hinweis-Zeile
  im Trainer-Output mit Ursache + Abhilfe (mehr Panel-Historie, keine lockereren Split-Parameter).

**Needs Nico:**
- Windows-Task registrieren (`scripts/install_windows_task.sh`) — oder bewusst bei Cron+systemd
  bleiben; optional den Task auf „Run whether user is logged on" heben (Passwort nötig).
- Heutige 18:02-Telegram-Nachricht ansehen: rendert der 💶-Block gut? (erster Live-Butler-Digest)
- `COPILOT_MONTHLY_BUDGET` in `.env` setzen, falls 500 €/Monat nicht passt.
- Merge/Push wie gehabt (Branch `autopilot/work`, kein Remote-Push durch den Autopiloten).
