# Cockpit Refresh Buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two buttons in the phone cockpit that start the data refresh on demand — "Tages-Update" (the daily chain) and "Alles aktualisieren" (full scout → daily → nightly) — with an honest "already ran / weekend" message plus an explicit force path, live step status and a log tail.

**Architecture:** The chains already exist and are already arbitrated by `scripts/run_*_guarded.sh` (flock + per-day/per-week marker). This plan adds three thin layers on top and changes no chain logic: (1) an `EQUITY_SCOUT_FORCE=1` env bypass for the marker and weekend guards inside the wrappers — the flock is *never* bypassed, so two chains can still never overlap; (2) `src/equity_scout/jobs.py`, a closed allowlist of job specs plus pure log/marker/lock readers, which hands a start off to `systemd-run --user` as its own transient unit (the dash service runs `KillMode=control-group`, so a plain child would die on any service restart, 20 minutes into a run); (3) `GET /api/jobs` + `POST /api/jobs/{key}/start` and a `RefreshPanel` as the first tab of Labor.

**Tech Stack:** FastAPI (existing `create_app`), stdlib `fcntl`/`subprocess`, bash wrappers, React 19 + TypeScript + Vite, pytest, vitest. No new dependencies.

---

## Context the implementer needs

**Where things live.** Repo root `~/private/equity-scout`. The dashboard is served by `scripts/run_api.py` behind a systemd user unit `equity-scout-dash.service` (`WorkingDirectory=%h/private/equity-scout`, binds `0.0.0.0:8420`, `EnvironmentFile=.env`). Every request passes the `DASH_TOKEN` middleware in `api.py` — loopback is exempt, everything else needs `?token=`, the `X-Dash-Token` header, or the `es_dash` cookie. That gate covers the new POST route with no extra work.

**The three chains and their bookkeeping:**

| chain | wrapper | chain script | log | marker | lock |
|---|---|---|---|---|---|
| daily (~26 min) | `scripts/run_daily_guarded.sh` | `scripts/daily_copilot.sh` | `copilot.log` | `.state/daily_last_run` (day) | `.state/daily.lock` |
| nightly (~2.5 min) | `scripts/run_nightly_guarded.sh` | `scripts/nightly_train.sh` | `train.log` | `.state/nightly_last_run` (day) | `.state/nightly.lock` |
| weekly full scout (long) | `scripts/run_weekly_guarded.sh` | `scripts/scheduled_run.sh` | `scout_full.log` | `.state/weekly_last_run` (ISO week) | `.state/weekly.lock` |

`daily_copilot.sh` and `nightly_train.sh` both wrap each step in a `step()` helper that appends `[<iso>] START <name>`, then `[<iso>] OK <name>` or `[<iso>] FAILED <name> (exit N) — continuing`, and bracket the run with `[<iso>] ===== <chain> start =====` / `===== <chain> end =====`. **That is the progress feed** — no new logging is needed. `scheduled_run.sh` has no step markers (it is a single `exec` into `run_scout.py`), so the full-refresh wrapper supplies the phase markers instead.

**Two decisions already made with Nico (2026-08-09), do not re-litigate:**
- The daily button reports a blocked state first ("lief heute schon" / "heute ist Wochenende") and only forces on a second, explicit tap.
- "Alles aktualisieren" is by definition the explicit "redo everything" button, so it **always** sends `force: true`. Its panel shows when each of the three phases last ran, and the button needs a confirm tap, because the run is hours long. Without force, its daily phase would silently skip on a weekend and the whole button would look broken.

**Why force must not touch the flock:** all three chains write the same SQLite databases. The marker prevents *redundant* runs; the flock prevents *concurrent* ones. Bypassing the marker is a user decision; bypassing the lock would be a data-corruption bug.

---

## File Structure

**Create:**
- `src/equity_scout/jobs.py` — job allowlist, pure status readers (log progress, marker, lock), start command builder, `systemd-run` launcher. One responsibility: "what are the manual chain triggers and what is their state right now".
- `scripts/run_full_refresh.sh` — the "everything" wrapper: own lock, own log, three `step()` phases calling the existing guarded wrappers.
- `tests/test_jobs.py` — pure-function tests for `jobs.py` (no processes started).
- `tests/test_api_jobs.py` — TestClient tests for both routes, launcher monkeypatched.
- `tests/test_run_daily_guarded.py` — the daily wrapper currently has no test file; force + weekend + marker behaviour gets one (mirrors `tests/test_run_weekly_guarded.py`).
- `tests/test_run_full_refresh.py` — end-to-end wrapper test with all three sub-chains stubbed via their existing seams.
- `frontend/src/jobs.ts` — pure presentation helpers (progress sentence, minutes, marker date formatting).
- `frontend/src/jobs.test.ts` — vitest for those helpers.
- `frontend/src/components/RefreshPanel.tsx` — the panel with both buttons, polling, tail.

**Modify:**
- `scripts/run_daily_guarded.sh` — `EQUITY_SCOUT_FORCE` bypass + `EQUITY_SCOUT_DAILY_LOG`/`_STATE` test seams (nightly/weekly already have theirs).
- `scripts/run_nightly_guarded.sh`, `scripts/run_weekly_guarded.sh` — `EQUITY_SCOUT_FORCE` bypass only.
- `src/equity_scout/api.py` — two routes, inserted after the `/api/inbox/{pitch_id}/decision` route (~line 1519) so the write endpoints sit together.
- `frontend/src/api.ts` — job types + `fetchJobs` + `startJob`, appended at the end of the file next to the other fetchers.
- `frontend/src/components/LaborView.tsx` — new first tab `aktualisieren`.
- `frontend/src/views.ts` — `SHEET_NOTES.labor` mentions the refresh.
- `frontend/src/index.css` — panel styles.
- `README.md` — "Handy-Cockpit" section documents the buttons.

---

### Task 1: Force bypass + test seams in the daily wrapper

**Files:**
- Modify: `scripts/run_daily_guarded.sh`
- Test: `tests/test_run_daily_guarded.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_daily_guarded.py`:

```python
"""Daily guard wrapper: weekday + marker arbitration, and the cockpit force bypass.

Mirrors tests/test_run_weekly_guarded.py. EQUITY_SCOUT_FORCE=1 is what the cockpit
button sends on an explicit second tap; it may skip the marker and the weekend guard
but must never skip the flock (concurrency is a data-integrity guard, not a policy one).
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
WRAPPER = REPO_DIR / "scripts" / "run_daily_guarded.sh"


def _run(tmp_path: Path, chain: Path, *, force: bool = False) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        EQUITY_SCOUT_CHAIN=str(chain),
        EQUITY_SCOUT_DAILY_STATE=str(tmp_path / "state"),
        EQUITY_SCOUT_DAILY_LOG=str(tmp_path / "copilot.log"),
    )
    if force:
        env["EQUITY_SCOUT_FORCE"] = "1"
    return subprocess.run(
        ["bash", str(WRAPPER), "test"], env=env, capture_output=True, text=True, timeout=30
    )


def _chain(tmp_path: Path, *, exit_code: int = 0) -> Path:
    counter = tmp_path / "runs"
    script = tmp_path / "chain.sh"
    script.write_text(f"#!/usr/bin/env bash\necho x >> {counter}\nexit {exit_code}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _runs(tmp_path: Path) -> int:
    counter = tmp_path / "runs"
    return len(counter.read_text().splitlines()) if counter.exists() else 0


def _is_weekend() -> bool:
    return subprocess.run(
        ["date", "+%u"], capture_output=True, text=True, check=True
    ).stdout.strip() > "5"


def test_forced_run_ignores_the_day_marker(tmp_path) -> None:
    chain = _chain(tmp_path)
    _run(tmp_path, chain, force=True)
    _run(tmp_path, chain, force=True)
    assert _runs(tmp_path) == 2  # marker did not arbitrate the second, explicit run away


def test_unforced_second_run_on_the_same_day_is_a_quiet_skip(tmp_path) -> None:
    if _is_weekend():
        chain = _chain(tmp_path)
        # On a weekend the FIRST run is already skipped, so seed the marker via a forced run.
        _run(tmp_path, chain, force=True)
        before = _runs(tmp_path)
        _run(tmp_path, chain)
        assert _runs(tmp_path) == before
        return
    chain = _chain(tmp_path)
    _run(tmp_path, chain)
    _run(tmp_path, chain)
    assert _runs(tmp_path) == 1


def test_forced_run_ignores_the_weekend_guard(tmp_path) -> None:
    chain = _chain(tmp_path)
    _run(tmp_path, chain, force=True)
    assert _runs(tmp_path) == 1  # runs on any weekday AND on a weekend


def test_forced_run_is_logged_as_forced(tmp_path) -> None:
    _run(tmp_path, _chain(tmp_path), force=True)
    log = (tmp_path / "copilot.log").read_text()
    assert "FORCED" in log


def test_failed_chain_leaves_the_day_unmarked_for_retry(tmp_path) -> None:
    _run(tmp_path, _chain(tmp_path, exit_code=3), force=True)
    assert not (tmp_path / "state" / "daily_last_run").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/private/equity-scout && .venv/bin/python -m pytest tests/test_run_daily_guarded.py -q`
Expected: FAIL — the wrapper ignores `EQUITY_SCOUT_DAILY_STATE`/`_LOG` (it writes to the real `.state/` and `copilot.log`), so `_runs()` and the marker assertions do not line up; `test_forced_run_ignores_the_day_marker` fails because there is no force path at all.

- [ ] **Step 3: Add the seams and the force bypass**

In `scripts/run_daily_guarded.sh`, replace the block from `REPO_DIR=` down to the end of the marker check with:

```bash
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${EQUITY_SCOUT_DAILY_LOG:-$REPO_DIR/copilot.log}"
STATE_DIR="${EQUITY_SCOUT_DAILY_STATE:-$REPO_DIR/.state}"
MARKER="$STATE_DIR/daily_last_run"
LOCK="$STATE_DIR/daily.lock"
CHAIN="${EQUITY_SCOUT_CHAIN:-$REPO_DIR/scripts/daily_copilot.sh}"
# The cockpit "Trotzdem starten" tap (2026-08-09): skips the marker and the weekend
# guard, never the flock — those two are policy, the lock is data integrity.
FORCE="${EQUITY_SCOUT_FORCE:-0}"
mkdir -p "$STATE_DIR"

# Weekdays only: a Saturday WSL start must not catch up Friday's missed slot.
# A persistent systemd catch-up firing on a weekend (e.g. WSL start on Saturday
# after a missed Friday) still stamps systemd's own timestamp file, permanently
# consuming that Friday catch-up — that's intended (weekends are never made up),
# but it must be diagnosable from copilot.log instead of vanishing silently.
if [ "$FORCE" != "1" ] && [ "$(date +%u)" -gt 5 ]; then
  echo "[$(date -Is)] guarded: weekend trigger (${1:-unspecified}) — skipped by design, missed weekday slots are not made up on weekends" >> "$LOG"
  exit 0
fi

exec 9>>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Is)] guarded: another daily run holds the lock (held by: $(cat "$LOCK" 2>/dev/null || echo unknown)) — skipping (trigger: ${1:-unspecified})" >> "$LOG"
  exit 0
fi

# Lock acquired: record who holds it (separate truncating write — FD 9 stays the
# flock handle and is unaffected) so a stuck run is diagnosable, not just detectable.
printf '%s pid=%s trigger=%s\n' "$(date -Is)" "$$" "${1:-unspecified}" > "$LOCK"

TODAY="$(date +%F)"
if [ "$FORCE" = "1" ]; then
  echo "[$(date -Is)] guarded: FORCED run (trigger: ${1:-unspecified}) — marker and weekend guard bypassed" >> "$LOG"
elif [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
  exit 0  # already ran today — quiet skip; redundant triggers are by design
fi
```

Leave the rest of the file (the `echo starting`, `"$CHAIN"`, `rc` handling and marker write) exactly as it is.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_run_daily_guarded.py -q`
Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_daily_guarded.sh tests/test_run_daily_guarded.py
git commit -m "feat: add force bypass and test seams to the daily guard wrapper"
```

---

### Task 2: Force bypass in the nightly and weekly wrappers

**Files:**
- Modify: `scripts/run_nightly_guarded.sh`, `scripts/run_weekly_guarded.sh`
- Test: `tests/test_run_nightly_guarded.py`, `tests/test_run_weekly_guarded.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_weekly_guarded.py`:

```python
def _run_forced(tmp_path: Path, chain: Path) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        EQUITY_SCOUT_WEEKLY_CHAIN=str(chain),
        EQUITY_SCOUT_WEEKLY_STATE=str(tmp_path / "state"),
        EQUITY_SCOUT_WEEKLY_LOG=str(tmp_path / "scout_full.log"),
        EQUITY_SCOUT_FORCE="1",
    )
    return subprocess.run(
        ["bash", str(WRAPPER), "test"], env=env, capture_output=True, text=True, timeout=30
    )


def test_forced_run_ignores_the_week_marker(tmp_path) -> None:
    chain = _chain(tmp_path)
    _run(tmp_path, chain)          # marks the week
    _run_forced(tmp_path, chain)   # cockpit "Trotzdem starten"
    assert _runs(tmp_path) == 2
    assert "FORCED" in (tmp_path / "scout_full.log").read_text()
```

Append to `tests/test_run_nightly_guarded.py` (it already defines `_run`, `_chain` and `_runs` with exactly these signatures, so only the forced variant is new):

```python
def _run_forced_nightly(tmp_path: Path, chain: Path) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        EQUITY_SCOUT_NIGHTLY_CHAIN=str(chain),
        EQUITY_SCOUT_NIGHTLY_STATE=str(tmp_path / "state"),
        EQUITY_SCOUT_NIGHTLY_LOG=str(tmp_path / "train.log"),
        EQUITY_SCOUT_FORCE="1",
    )
    return subprocess.run(
        ["bash", str(WRAPPER), "test"], env=env, capture_output=True, text=True, timeout=30
    )


def test_forced_run_ignores_the_day_marker(tmp_path) -> None:
    chain = _chain(tmp_path)
    _run(tmp_path, chain)
    _run_forced_nightly(tmp_path, chain)
    assert _runs(tmp_path) == 2
    assert "FORCED" in (tmp_path / "train.log").read_text()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_run_nightly_guarded.py tests/test_run_weekly_guarded.py -q`
Expected: the two new tests FAIL with `assert 1 == 2` — the marker still arbitrates the forced run away.

- [ ] **Step 3: Add the bypass to both wrappers**

In `scripts/run_nightly_guarded.sh`, after the `CHAIN=` line add:

```bash
# Cockpit "Trotzdem starten" (2026-08-09): marker bypass only, never the flock.
FORCE="${EQUITY_SCOUT_FORCE:-0}"
```

and replace the marker check with:

```bash
TODAY="$(date +%F)"
if [ "$FORCE" = "1" ]; then
  echo "[$(date -Is)] nightly-guarded: FORCED run (trigger: ${1:-unspecified}) — marker bypassed" >> "$LOG"
elif [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$TODAY" ]; then
  exit 0  # already ran today — quiet skip; redundant triggers are by design
fi
```

In `scripts/run_weekly_guarded.sh`, after the `CHAIN=` line add the same two lines, and replace the marker check with:

```bash
THIS_WEEK="$(date +%G-W%V)"
if [ "$FORCE" = "1" ]; then
  echo "[$(date -Is)] weekly-guarded: FORCED run (trigger: ${1:-unspecified}) — marker bypassed" >> "$LOG"
elif [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$THIS_WEEK" ]; then
  exit 0  # already ran this week — quiet skip; redundant triggers are by design
fi
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_run_nightly_guarded.py tests/test_run_weekly_guarded.py -q`
Expected: PASS, all tests in both files green.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_nightly_guarded.sh scripts/run_weekly_guarded.sh tests/test_run_nightly_guarded.py tests/test_run_weekly_guarded.py
git commit -m "feat: add force bypass to the nightly and weekly guard wrappers"
```

---

### Task 3: The full-refresh wrapper

**Files:**
- Create: `scripts/run_full_refresh.sh`
- Test: `tests/test_run_full_refresh.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_full_refresh.py`:

```python
"""Full refresh wrapper: the three guarded chains in dependency order, one lock, one log.

The three sub-chains are stubbed through their own EQUITY_SCOUT_*_CHAIN seams, so this
exercises the real wrappers (including their locks and markers) without running a scout.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
WRAPPER = REPO_DIR / "scripts" / "run_full_refresh.sh"


def _stub(tmp_path: Path, name: str) -> Path:
    """A chain stub that appends its own name to a shared order file."""
    order = tmp_path / "order"
    script = tmp_path / f"{name}.sh"
    script.write_text(f"#!/usr/bin/env bash\necho {name} >> {order}\nexit 0\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _run(tmp_path: Path, *, force: bool = True) -> subprocess.CompletedProcess:
    state = tmp_path / "state"
    env = dict(
        os.environ,
        EQUITY_SCOUT_FULL_LOG=str(tmp_path / "full_refresh.log"),
        EQUITY_SCOUT_FULL_STATE=str(state),
        EQUITY_SCOUT_WEEKLY_CHAIN=str(_stub(tmp_path, "scout")),
        EQUITY_SCOUT_WEEKLY_STATE=str(state),
        EQUITY_SCOUT_WEEKLY_LOG=str(tmp_path / "scout_full.log"),
        EQUITY_SCOUT_CHAIN=str(_stub(tmp_path, "daily")),
        EQUITY_SCOUT_DAILY_STATE=str(state),
        EQUITY_SCOUT_DAILY_LOG=str(tmp_path / "copilot.log"),
        EQUITY_SCOUT_NIGHTLY_CHAIN=str(_stub(tmp_path, "nightly")),
        EQUITY_SCOUT_NIGHTLY_STATE=str(state),
        EQUITY_SCOUT_NIGHTLY_LOG=str(tmp_path / "train.log"),
    )
    if force:
        env["EQUITY_SCOUT_FORCE"] = "1"
    return subprocess.run(
        ["bash", str(WRAPPER), "test"], env=env, capture_output=True, text=True, timeout=60
    )


def test_runs_all_three_phases_in_dependency_order(tmp_path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0
    order = (tmp_path / "order").read_text().split()
    assert order == ["scout", "daily", "nightly"]


def test_log_carries_the_session_and_step_markers(tmp_path) -> None:
    _run(tmp_path)
    log = (tmp_path / "full_refresh.log").read_text()
    assert "===== full_refresh start =====" in log
    assert "===== full_refresh end =====" in log
    for phase in ("scout", "daily", "nightly"):
        assert f"START {phase}" in log
        assert f"OK {phase}" in log


def test_a_failing_phase_does_not_stop_the_rest(tmp_path) -> None:
    failing = tmp_path / "scout.sh"
    _run(tmp_path)  # creates the stubs
    failing.write_text("#!/usr/bin/env bash\nexit 4\n")
    (tmp_path / "order").unlink()
    result = _run(tmp_path)
    assert result.returncode == 0
    order = (tmp_path / "order").read_text().split()
    assert order == ["daily", "nightly"]  # scout failed, the chain kept going
    assert "FAILED scout" in (tmp_path / "full_refresh.log").read_text()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_run_full_refresh.py -q`
Expected: FAIL — `scripts/run_full_refresh.sh` does not exist (bash exits 127).

- [ ] **Step 3: Write the wrapper**

Create `scripts/run_full_refresh.sh`:

```bash
#!/usr/bin/env bash
# Cockpit "Alles aktualisieren" (2026-08-09): the three scheduler chains in dependency
# order — full scout first (it refreshes the run snapshot the watchlist ranks from), then
# the daily chain, then the nightly training/depot advance.
#
# This wrapper adds no arbitration beyond its own lock: each phase is an existing guarded
# wrapper that keeps its own flock and marker. EQUITY_SCOUT_FORCE reaches them by env
# inheritance — the cockpit always sets it for this button, because an unforced full
# refresh would silently skip whichever phase already ran today and the button would
# look broken.
#
# Every phase is a step() so the cockpit can read the phase from this one log; the
# per-phase detail stays in scout_full.log / copilot.log / train.log.
# Test seams: EQUITY_SCOUT_FULL_LOG, EQUITY_SCOUT_FULL_STATE.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${EQUITY_SCOUT_FULL_LOG:-$REPO_DIR/full_refresh.log}"
STATE_DIR="${EQUITY_SCOUT_FULL_STATE:-$REPO_DIR/.state}"
LOCK="$STATE_DIR/full_refresh.lock"
TRIGGER="${1:-unspecified}"
mkdir -p "$STATE_DIR"

exec 9>>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Is)] full_refresh: another full refresh holds the lock (held by: $(cat "$LOCK" 2>/dev/null || echo unknown)) — skipping (trigger: $TRIGGER)" >> "$LOG"
  exit 0
fi
printf '%s pid=%s trigger=%s\n' "$(date -Is)" "$$" "$TRIGGER" > "$LOCK"

# Same contract as daily_copilot.sh: a failing phase is logged and the chain continues,
# so one rate-limited scout cannot cost the daily and nightly refresh behind it.
step() {
  local name="$1"
  shift
  echo "[$(date -Is)] START ${name}" >> "$LOG"
  if "$@" >> "$LOG" 2>&1; then
    echo "[$(date -Is)] OK ${name}" >> "$LOG"
  else
    local rc=$?
    echo "[$(date -Is)] FAILED ${name} (exit ${rc}) — continuing" >> "$LOG"
  fi
}

echo "[$(date -Is)] ===== full_refresh start ===== (trigger: $TRIGGER)" >> "$LOG"
step scout   "$REPO_DIR/scripts/run_weekly_guarded.sh"  "$TRIGGER"
step daily   "$REPO_DIR/scripts/run_daily_guarded.sh"   "$TRIGGER"
step nightly "$REPO_DIR/scripts/run_nightly_guarded.sh" "$TRIGGER"
echo "[$(date -Is)] ===== full_refresh end =====" >> "$LOG"
```

Then make it executable:

```bash
chmod +x scripts/run_full_refresh.sh
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_run_full_refresh.py -q`
Expected: PASS, 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_full_refresh.sh tests/test_run_full_refresh.py
git commit -m "feat: add full-refresh wrapper chaining scout, daily and nightly"
```

---

### Task 4: Job specs and pure status readers

**Files:**
- Create: `src/equity_scout/jobs.py`
- Test: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_jobs.py`:

```python
"""Manual chain triggers: the allowlist, the log/marker/lock readers, the start command.

Everything here is pure or filesystem-only — no test starts a chain or touches systemd.
"""
from __future__ import annotations

import fcntl
from datetime import date, datetime
from pathlib import Path

from equity_scout.jobs import (
    JOBS,
    blocked_reason,
    build_start_command,
    busy_lock,
    job_status,
    lock_held,
    marker_value,
    parse_progress,
    tail_lines,
)

DAILY_LOG = """[2026-08-07T18:00:00+02:00] ===== daily_copilot start =====
[2026-08-07T18:00:01+02:00] START radar
[2026-08-07T18:01:30+02:00] OK radar
[2026-08-07T18:01:31+02:00] START insights
[2026-08-07T18:04:10+02:00] FAILED insights (exit 1) — continuing
[2026-08-07T18:04:11+02:00] START earnings
"""


def test_parse_progress_reports_the_running_step_and_the_finished_count() -> None:
    progress = parse_progress(DAILY_LOG, JOBS["daily"].steps)
    assert progress["current"] == "earnings"
    assert progress["done_count"] == 2  # radar OK + insights FAILED are both finished
    assert progress["failed"] == ["insights"]
    assert progress["expected_total"] == 12
    assert progress["started_at"] == "2026-08-07T18:00:00+02:00"
    assert progress["current_since"] == "2026-08-07T18:04:11+02:00"


def test_parse_progress_ignores_everything_before_the_last_session_start() -> None:
    text = DAILY_LOG + """[2026-08-08T18:00:00+02:00] ===== daily_copilot start =====
[2026-08-08T18:00:01+02:00] START radar
"""
    progress = parse_progress(text, JOBS["daily"].steps)
    assert progress["current"] == "radar"
    assert progress["done_count"] == 0
    assert progress["failed"] == []


def test_parse_progress_on_a_finished_run_has_no_current_step() -> None:
    text = DAILY_LOG + "[2026-08-07T18:26:00+02:00] OK earnings\n"
    progress = parse_progress(text, JOBS["daily"].steps)
    assert progress["current"] is None
    assert progress["done_count"] == 3


def test_parse_progress_on_an_empty_log_is_all_zero() -> None:
    progress = parse_progress("", JOBS["daily"].steps)
    assert progress["current"] is None
    assert progress["done_count"] == 0
    assert progress["started_at"] is None


def test_tail_lines_returns_the_last_lines_only(tmp_path) -> None:
    log = tmp_path / "x.log"
    log.write_text("\n".join(f"line {i}" for i in range(100)) + "\n")
    assert tail_lines(log, 3) == ["line 97", "line 98", "line 99"]


def test_tail_lines_on_a_missing_file_is_empty(tmp_path) -> None:
    assert tail_lines(tmp_path / "nope.log", 5) == []


def test_lock_held_is_false_for_a_free_and_a_missing_lock(tmp_path) -> None:
    assert lock_held(tmp_path / "missing.lock") is False
    free = tmp_path / "free.lock"
    free.write_text("stale content from a finished run\n")
    assert lock_held(free) is False  # the file survives the run, the flock does not


def test_lock_held_is_true_while_another_handle_holds_the_flock(tmp_path) -> None:
    held = tmp_path / "held.lock"
    held.write_text("")
    with held.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert lock_held(held) is True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    assert lock_held(held) is False


def test_marker_value_reads_and_strips(tmp_path) -> None:
    marker = tmp_path / "daily_last_run"
    marker.write_text("2026-08-07\n")
    assert marker_value(marker) == "2026-08-07"
    assert marker_value(tmp_path / "absent") is None


def test_blocked_reason_reports_already_ran_for_todays_marker(tmp_path) -> None:
    (tmp_path / ".state").mkdir()
    (tmp_path / ".state" / "daily_last_run").write_text("2026-08-10")
    # 2026-08-10 is a Monday, so the weekend guard is not what blocks here.
    assert blocked_reason(JOBS["daily"], tmp_path, today=date(2026, 8, 10)) == "already_ran"


def test_blocked_reason_reports_weekend_when_the_marker_is_stale(tmp_path) -> None:
    (tmp_path / ".state").mkdir()
    (tmp_path / ".state" / "daily_last_run").write_text("2026-08-07")
    # 2026-08-09 is a Sunday: the wrapper's weekday guard would skip the run.
    assert blocked_reason(JOBS["daily"], tmp_path, today=date(2026, 8, 9)) == "weekend"


def test_blocked_reason_is_none_on_a_weekday_with_a_stale_marker(tmp_path) -> None:
    (tmp_path / ".state").mkdir()
    (tmp_path / ".state" / "daily_last_run").write_text("2026-08-07")
    assert blocked_reason(JOBS["daily"], tmp_path, today=date(2026, 8, 10)) is None


def test_the_full_job_is_never_marker_blocked(tmp_path) -> None:
    # It has no marker of its own: it is the explicit "redo everything" button and
    # always runs forced, so its phases' markers must not gate the button.
    assert blocked_reason(JOBS["full"], tmp_path, today=date(2026, 8, 9)) is None


def test_busy_lock_names_the_blocking_sub_chain_for_the_full_job(tmp_path) -> None:
    state = tmp_path / ".state"
    state.mkdir()
    daily = state / "daily.lock"
    daily.write_text("")
    with daily.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert busy_lock(JOBS["full"], tmp_path) == ".state/daily.lock"
        assert busy_lock(JOBS["daily"], tmp_path) == ".state/daily.lock"
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    assert busy_lock(JOBS["full"], tmp_path) is None


def test_build_start_command_is_a_systemd_unit_with_no_request_data() -> None:
    cmd = build_start_command(JOBS["daily"], Path("/repo"), force=False, unit_suffix="1")
    assert cmd[:3] == ["systemd-run", "--user", "--collect"]
    assert "--unit=es-job-daily-1" in cmd
    assert "--working-directory=/repo" in cmd
    assert cmd[-2:] == ["/repo/scripts/run_daily_guarded.sh", "cockpit"]
    assert "--setenv=EQUITY_SCOUT_FORCE=1" not in cmd


def test_build_start_command_passes_force_as_an_env_var() -> None:
    cmd = build_start_command(JOBS["full"], Path("/repo"), force=True, unit_suffix="2")
    assert "--setenv=EQUITY_SCOUT_FORCE=1" in cmd
    assert cmd[-2:] == ["/repo/scripts/run_full_refresh.sh", "cockpit"]


def test_job_status_shape_for_the_daily_job(tmp_path) -> None:
    (tmp_path / ".state").mkdir()
    (tmp_path / ".state" / "daily_last_run").write_text("2026-08-07")
    (tmp_path / "copilot.log").write_text(DAILY_LOG)
    status = job_status(JOBS["daily"], tmp_path, now=datetime(2026, 8, 9, 12, 0))
    assert status["key"] == "daily"
    assert status["label"] == "Tages-Update"
    assert status["running"] is False
    assert status["blocked"] == "weekend"
    assert status["last_run"] == "2026-08-07"
    assert status["progress"]["current"] == "earnings"
    assert status["tail"][-1].startswith("[2026-08-07T18:04:11")
    assert "sub_runs" not in status


def test_job_status_for_the_full_job_lists_the_three_phase_markers(tmp_path) -> None:
    state = tmp_path / ".state"
    state.mkdir()
    (state / "daily_last_run").write_text("2026-08-07")
    (state / "nightly_last_run").write_text("2026-08-08")
    status = job_status(JOBS["full"], tmp_path, now=datetime(2026, 8, 9, 12, 0))
    assert status["sub_runs"] == {"scout": None, "daily": "2026-08-07", "nightly": "2026-08-08"}
    assert status["blocked"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_jobs.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'equity_scout.jobs'`.

- [ ] **Step 3: Write the module**

Create `src/equity_scout/jobs.py`:

```python
"""Manual chain triggers for the phone cockpit (2026-08-09).

The daily/nightly/weekly chains are scheduler-driven and arbitrated by the
run_*_guarded.sh wrappers (flock + per-day/per-week marker). This module adds the one
thing no scheduler can do: let Nico start a refresh from the phone, right now.

Two rules carry the design:

- The job list is a CLOSED allowlist of key -> script. Nothing from an HTTP body ever
  reaches a command line; a request picks a key and a force flag, nothing else.
- A start is handed to systemd as its own transient unit. equity-scout-dash.service runs
  with the default KillMode=control-group, so a plain child process would be killed by any
  restart of the dashboard — twenty minutes into a twenty-six minute chain.

Progress comes from the logs the chains already write: daily_copilot.sh, nightly_train.sh
and run_full_refresh.sh all bracket a run with "===== <name> start =====" and wrap each
step as "START <step>" then "OK <step>" or "FAILED <step> (exit N)". No new logging.
"""
from __future__ import annotations

import fcntl
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# src/equity_scout/jobs.py -> src/equity_scout -> src -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

# How many log lines the cockpit SHOWS. Enough to see a traceback's last frames without
# shipping a megabyte of log to a phone on mobile data.
TAIL_LINES = 25
# How much of a log is read for PARSING. The chains redirect each step's stdout into the
# same log ("$@" >> "$LOG" 2>&1), so a run is not a handful of lines: a Friday daily run
# measured 80 lines / 72 KB total, but a Monday one also carries the full scout's output.
# The window has to reach back past the run's "===== start =====" line or parse_progress
# sees no session and reports nothing — 256 KB covers a scout-sized run with room to
# spare, and it never leaves the server.
_TAIL_BYTES = 256 * 1024
# Line budget for the same reason; only TAIL_LINES of it is ever sent to the client.
_PARSE_LINES = 4000

_STEP_RE = re.compile(r"^\[(?P<ts>[^\]]+)\] (?P<kind>START|OK|FAILED) (?P<name>[A-Za-z0-9_]+)")
_SESSION_RE = re.compile(r"^\[(?P<ts>[^\]]+)\] ===== \S+ start =====")


@dataclass(frozen=True)
class JobSpec:
    """One manually startable chain. Paths are repo-relative and fixed at import time."""

    key: str
    label: str
    script: str
    log: str
    lock: str
    steps: tuple[str, ...]
    marker: str | None = None
    marker_kind: str = "day"  # "day" | "week"
    weekend_blocked: bool = False
    # Extra locks that must also be free — the full refresh drives the other three
    # wrappers, so a running daily chain blocks it just as much as a running full one.
    blocks_on: tuple[str, ...] = ()
    # Phase -> the log that phase writes its detail to (full refresh only).
    detail_logs: dict[str, str] = field(default_factory=dict)
    # Phase -> marker, so the panel can show when each phase last ran (full refresh only).
    sub_markers: dict[str, str] = field(default_factory=dict)


# The daily chain's steps in daily_copilot.sh order. On Mondays it prepends "scout" and
# "person_scores", so the count is a floor, not a contract — the cockpit says "von ~12".
DAILY_STEPS = (
    "radar",
    "insights",
    "earnings",
    "evidence",
    "fscore",
    "notify",
    "score_watchlist",
    "resolve_predictions",
    "resolve_evidence",
    "resolve_events",
    "lanes",
    "digest",
)

JOBS: dict[str, JobSpec] = {
    "daily": JobSpec(
        key="daily",
        label="Tages-Update",
        script="scripts/run_daily_guarded.sh",
        log="copilot.log",
        lock=".state/daily.lock",
        marker=".state/daily_last_run",
        marker_kind="day",
        weekend_blocked=True,
        steps=DAILY_STEPS,
    ),
    "full": JobSpec(
        key="full",
        label="Alles aktualisieren",
        script="scripts/run_full_refresh.sh",
        log="full_refresh.log",
        lock=".state/full_refresh.lock",
        marker=None,  # the explicit "redo everything" button: its phases hold the markers
        steps=("scout", "daily", "nightly"),
        blocks_on=(".state/weekly.lock", ".state/daily.lock", ".state/nightly.lock"),
        detail_logs={"scout": "scout_full.log", "daily": "copilot.log", "nightly": "train.log"},
        sub_markers={
            "scout": ".state/weekly_last_run",
            "daily": ".state/daily_last_run",
            "nightly": ".state/nightly_last_run",
        },
    ),
}


def parse_progress(text: str, steps: tuple[str, ...]) -> dict:
    """Step progress of the LAST run in a chain log.

    Everything before the final "===== ... start =====" belongs to an earlier run and is
    ignored — otherwise yesterday's finished steps would inflate today's count.
    """
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if _SESSION_RE.match(line):
            start_idx = i
    if start_idx is None:
        return {
            "current": None,
            "current_since": None,
            "done_count": 0,
            "failed": [],
            "expected_total": len(steps),
            "started_at": None,
        }

    started_at = _SESSION_RE.match(lines[start_idx]).group("ts")
    current: str | None = None
    current_since: str | None = None
    done: list[str] = []
    failed: list[str] = []
    for line in lines[start_idx + 1 :]:
        match = _STEP_RE.match(line)
        if match is None:
            continue
        kind, name, ts = match.group("kind"), match.group("name"), match.group("ts")
        if kind == "START":
            current, current_since = name, ts
        else:
            done.append(name)
            if kind == "FAILED":
                failed.append(name)
            if current == name:
                current, current_since = None, None
    return {
        "current": current,
        "current_since": current_since,
        "done_count": len(done),
        "failed": failed,
        "expected_total": len(steps),
        "started_at": started_at,
    }


def tail_lines(path: Path, count: int) -> list[str]:
    """Last `count` lines, reading at most the final _TAIL_BYTES. Missing file -> []."""
    if not path.exists():
        return []
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - _TAIL_BYTES))
        chunk = fh.read()
    text = chunk.decode("utf-8", errors="replace")
    return text.splitlines()[-count:]


def lock_held(path: Path) -> bool:
    """True while another process holds the flock on `path`.

    The lock FILE outlives every run (the wrappers open it append-only), so its existence
    proves nothing — only the flock does. Testing it means taking it and letting go
    immediately; the wrapper takes its own lock anyway, so a lost race costs nothing.
    """
    if not path.exists():
        return False
    with path.open("a") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return False


def marker_value(path: Path) -> str | None:
    if not path.exists():
        return None
    value = path.read_text().strip()
    return value or None


def busy_lock(spec: JobSpec, root: Path) -> str | None:
    """The repo-relative lock path currently blocking this job, or None."""
    for rel in (spec.lock, *spec.blocks_on):
        if lock_held(root / rel):
            return rel
    return None


def blocked_reason(spec: JobSpec, root: Path, *, today: date) -> str | None:
    """Why an UNFORCED start would do nothing: "already_ran", "weekend", or None."""
    if spec.marker is not None:
        stamp = today.isoformat() if spec.marker_kind == "day" else today.strftime("%G-W%V")
        if marker_value(root / spec.marker) == stamp:
            return "already_ran"
    if spec.weekend_blocked and today.isoweekday() > 5:
        return "weekend"
    return None


def job_status(spec: JobSpec, root: Path = REPO_ROOT, *, now: datetime) -> dict:
    """Everything the cockpit panel renders for one job."""
    running = busy_lock(spec, root) is not None
    log_text = "\n".join(tail_lines(root / spec.log, _PARSE_LINES))
    progress = parse_progress(log_text, spec.steps)
    # While a full refresh runs, the interesting lines are the ones its CURRENT phase
    # writes — full_refresh.log only carries the three phase markers.
    tail_log = spec.detail_logs.get(progress["current"] or "", spec.log)
    status: dict = {
        "key": spec.key,
        "label": spec.label,
        "running": running,
        "blocked": blocked_reason(spec, root, today=now.date()),
        "last_run": marker_value(root / spec.marker) if spec.marker else None,
        "progress": progress,
        "tail": tail_lines(root / tail_log, TAIL_LINES),
    }
    if spec.sub_markers:
        status["sub_runs"] = {
            phase: marker_value(root / rel) for phase, rel in spec.sub_markers.items()
        }
    return status


def build_start_command(
    spec: JobSpec, root: Path, *, force: bool, unit_suffix: str
) -> list[str]:
    """The systemd-run argv. Only `spec` and `force` shape it — never request data."""
    cmd = [
        "systemd-run",
        "--user",
        "--collect",  # drop the transient unit once it exits
        f"--unit=es-job-{spec.key}-{unit_suffix}",
        f"--working-directory={root}",
        f"--description=equity-scout {spec.label} (Cockpit)",
    ]
    if force:
        cmd.append("--setenv=EQUITY_SCOUT_FORCE=1")
    cmd.append(str(root / spec.script))
    cmd.append("cockpit")  # the trigger name the wrappers write into their logs
    return cmd


def start_job(spec: JobSpec, root: Path = REPO_ROOT, *, force: bool) -> None:
    """Hand the chain to systemd. Raises subprocess.CalledProcessError if it refuses."""
    cmd = build_start_command(spec, root, force=force, unit_suffix=str(int(time.time())))
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=20)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_jobs.py -q`
Expected: PASS, 18 passed.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check src/equity_scout/jobs.py tests/test_jobs.py
git add src/equity_scout/jobs.py tests/test_jobs.py
git commit -m "feat: add job specs and status readers for manual chain triggers"
```

---

### Task 5: The two API routes

**Files:**
- Modify: `src/equity_scout/api.py` (insert after the `/api/inbox/{pitch_id}/decision` route, currently ending ~line 1519)
- Test: `tests/test_api_jobs.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_jobs.py`:

```python
"""Cockpit job routes: status, the honest "would do nothing" answer, and the force path.

No test starts a chain: equity_scout.jobs.start_job is monkeypatched, and the assertions
are about what the route decides, not about systemd.
"""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from equity_scout import jobs as jobs_mod
from equity_scout.api import create_app


@pytest.fixture
def client(tmp_path) -> TestClient:
    return TestClient(create_app(str(tmp_path / "equity_scout.db")))


@pytest.fixture
def started(monkeypatch) -> list[tuple[str, bool]]:
    """Records (job key, force) instead of launching anything.

    Also pins busy_lock to "free": without it these tests read the repo's real .state
    locks and would flip to 409 whenever a chain happens to be running on this machine.
    The one test that cares about the lock overrides it again.
    """
    calls: list[tuple[str, bool]] = []

    def fake_start(spec, root=jobs_mod.REPO_ROOT, *, force: bool) -> None:
        calls.append((spec.key, force))

    monkeypatch.setattr(jobs_mod, "start_job", fake_start)
    monkeypatch.setattr(jobs_mod, "busy_lock", lambda spec, root: None)
    return calls


def test_status_lists_both_jobs_with_their_labels(client) -> None:
    response = client.get("/api/jobs")
    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert [job["key"] for job in jobs] == ["daily", "full"]
    assert jobs[0]["label"] == "Tages-Update"
    for job in jobs:
        assert set(job) >= {"running", "blocked", "progress", "tail"}


def test_unknown_job_is_a_404(client, started) -> None:
    response = client.post("/api/jobs/rm-rf/start", json={"force": False})
    assert response.status_code == 404
    assert started == []


def test_start_reports_the_blocked_reason_instead_of_starting(client, started, monkeypatch) -> None:
    monkeypatch.setattr(jobs_mod, "blocked_reason", lambda spec, root, *, today: "already_ran")
    response = client.post("/api/jobs/daily/start", json={"force": False})
    assert response.status_code == 200
    body = response.json()
    assert body["started"] is False
    assert body["reason"] == "already_ran"
    assert started == []  # nothing launched — the panel now offers "Trotzdem starten"


def test_force_starts_even_when_blocked(client, started, monkeypatch) -> None:
    monkeypatch.setattr(jobs_mod, "blocked_reason", lambda spec, root, *, today: "weekend")
    response = client.post("/api/jobs/daily/start", json={"force": True})
    assert response.status_code == 200
    assert response.json()["started"] is True
    assert response.json()["forced"] is True
    assert started == [("daily", True)]


def test_start_is_refused_while_a_lock_is_held(client, started, monkeypatch) -> None:
    # Overrides the fixture's "free" lock on purpose.
    monkeypatch.setattr(jobs_mod, "busy_lock", lambda spec, root: ".state/daily.lock")
    response = client.post("/api/jobs/daily/start", json={"force": True})
    assert response.status_code == 409
    assert started == []  # force never bypasses the lock — two chains, one database


def test_a_refused_launch_surfaces_as_a_500_with_the_reason(client, started, monkeypatch) -> None:
    def boom(spec, root=jobs_mod.REPO_ROOT, *, force: bool) -> None:
        raise subprocess.CalledProcessError(1, ["systemd-run"], stderr="Unit already exists.")

    monkeypatch.setattr(jobs_mod, "start_job", boom)
    monkeypatch.setattr(jobs_mod, "blocked_reason", lambda spec, root, *, today: None)
    response = client.post("/api/jobs/daily/start", json={"force": False})
    assert response.status_code == 500
    assert "Unit already exists." in response.json()["error"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_jobs.py -q`
Expected: FAIL — `GET /api/jobs` returns 404 (the route does not exist).

- [ ] **Step 3: Add the routes**

In `src/equity_scout/api.py`, directly after the closing of the `/api/inbox/{pitch_id}/decision` route (the `return JSONResponse({"ok": True, "pitch": ..., "disclaimer": DISCLAIMER})` block) and before `@app.get("/api/arena")`, insert:

```python
    # --- Manual chain triggers (cockpit refresh buttons, 2026-08-09) ---
    # The module is imported lazily and its functions are looked up through the module
    # object on every call, so tests can monkeypatch start_job/busy_lock/blocked_reason.
    @app.get("/api/jobs")
    def jobs_status() -> JSONResponse:
        from equity_scout import jobs as jobs_mod

        now = datetime.now()
        return JSONResponse(
            {
                "jobs": [
                    jobs_mod.job_status(spec, jobs_mod.REPO_ROOT, now=now)
                    for spec in jobs_mod.JOBS.values()
                ],
                "disclaimer": DISCLAIMER,
            }
        )

    @app.post("/api/jobs/{key}/start")
    def jobs_start(key: str, body: dict) -> JSONResponse:
        from equity_scout import jobs as jobs_mod

        spec = jobs_mod.JOBS.get(key)
        if spec is None:
            return JSONResponse({"error": "Unbekannter Job."}, status_code=404)
        force = bool((body or {}).get("force"))
        root = jobs_mod.REPO_ROOT

        # The lock is never bypassed, not even by force: all chains write the same
        # SQLite databases, so concurrency is an integrity guard, not a policy one.
        busy = jobs_mod.busy_lock(spec, root)
        if busy is not None:
            return JSONResponse(
                {
                    "error": f"Läuft bereits ({busy}).",
                    "job": jobs_mod.job_status(spec, root, now=datetime.now()),
                },
                status_code=409,
            )

        reason = jobs_mod.blocked_reason(spec, root, today=date.today())
        if reason is not None and not force:
            # Nothing started, and the panel says so — an unforced start would have been
            # a quiet no-op inside the wrapper, which is exactly what must not happen
            # behind a button.
            return JSONResponse(
                {
                    "started": False,
                    "reason": reason,
                    "job": jobs_mod.job_status(spec, root, now=datetime.now()),
                }
            )

        try:
            jobs_mod.start_job(spec, root, force=force)
        except (subprocess.CalledProcessError, OSError) as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            return JSONResponse(
                {"error": f"Start fehlgeschlagen: {detail}"}, status_code=500
            )
        return JSONResponse(
            {
                "started": True,
                "forced": force,
                "job": jobs_mod.job_status(spec, root, now=datetime.now()),
            }
        )
```

Then make sure the imports the routes need exist at the top of `api.py`. Check the current import block and add whatever is missing:

```bash
grep -nE "^(import|from) (subprocess|datetime)" src/equity_scout/api.py
grep -n "^from datetime import" src/equity_scout/api.py
```

`api.py` already imports `datetime` and `timezone` from `datetime` (used by `inbox_decision`). Add `date` to that same import, and add `import subprocess` to the stdlib import block, keeping alphabetical order:

```python
from datetime import date, datetime, timezone
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_jobs.py -q`
Expected: PASS, 6 passed.

- [ ] **Step 5: Verify the token gate covers the new routes**

Run:
```bash
.venv/bin/python -m pytest tests/test_api_auth.py -q
.venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from equity_scout.api import create_app
c = TestClient(create_app("/tmp/es-jobs-check.db", dash_token="geheim"))
print("GET  /api/jobs          ->", c.get("/api/jobs").status_code)
print("POST /api/jobs/daily/…  ->", c.post("/api/jobs/daily/start", json={"force": False}).status_code)
PY
```
Expected: `test_api_auth.py` green, and both printed statuses are **401** — the TestClient's host is not loopback, so the middleware rejects both routes without a token.

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/python -m ruff check src/equity_scout/api.py tests/test_api_jobs.py
git add src/equity_scout/api.py tests/test_api_jobs.py
git commit -m "feat: add job status and start endpoints for the cockpit refresh"
```

---

### Task 6: Frontend API client and presentation helpers

**Files:**
- Modify: `frontend/src/api.ts` (append at the end, after `fetchCompany`)
- Create: `frontend/src/jobs.ts`, `frontend/src/jobs.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/jobs.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import type { JobState } from "./api";
import { blockedText, describeProgress, formatMarker } from "./jobs";

const RUNNING: JobState = {
  key: "daily",
  label: "Tages-Update",
  running: true,
  blocked: null,
  last_run: "2026-08-07",
  progress: {
    current: "evidence",
    current_since: "2026-08-09T21:00:00+02:00",
    done_count: 3,
    expected_total: 12,
    failed: [],
    started_at: "2026-08-09T20:54:00+02:00",
  },
  tail: [],
};

const IDLE: JobState = { ...RUNNING, running: false, progress: { ...RUNNING.progress, current: null } };

describe("describeProgress", () => {
  it("names the running step, its number and how long it has been running", () => {
    const now = new Date("2026-08-09T21:06:00+02:00").getTime();
    expect(describeProgress(RUNNING, now)).toBe("Schritt 4 von ~12: evidence · seit 6 Min.");
  });

  it("falls back to the total runtime when no step has started yet", () => {
    const job: JobState = {
      ...RUNNING,
      progress: { ...RUNNING.progress, current: null, current_since: null, done_count: 0 },
    };
    const now = new Date("2026-08-09T20:56:00+02:00").getTime();
    expect(describeProgress(job, now)).toBe("läuft seit 2 Min.");
  });

  it("reports failed steps of a running chain", () => {
    const job: JobState = { ...RUNNING, progress: { ...RUNNING.progress, failed: ["notify"] } };
    const now = new Date("2026-08-09T21:06:00+02:00").getTime();
    expect(describeProgress(job, now)).toContain("1 Schritt fehlgeschlagen");
  });

  it("says when the job is idle", () => {
    expect(describeProgress(IDLE, Date.now())).toBe("läuft nicht");
  });
});

describe("formatMarker", () => {
  it("renders a day marker as a German date", () => {
    expect(formatMarker("2026-08-07")).toBe("07.08.2026");
  });

  it("leaves an ISO week marker as is", () => {
    expect(formatMarker("2026-W32")).toBe("KW 32/2026");
  });

  it("says never for a missing marker", () => {
    expect(formatMarker(null)).toBe("noch nie");
  });
});

describe("blockedText", () => {
  it("explains the weekend guard", () => {
    expect(blockedText("weekend")).toContain("Wochenende");
  });

  it("explains the day marker", () => {
    expect(blockedText("already_ran")).toContain("schon gelaufen");
  });

  it("is empty when nothing blocks", () => {
    expect(blockedText(null)).toBe("");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/private/equity-scout/frontend && npm test -- jobs`
Expected: FAIL — `Failed to resolve import "./jobs"`.

- [ ] **Step 3: Add the API types and the helpers**

Append to `frontend/src/api.ts`:

```ts
// --- Manual chain triggers (src/equity_scout/api.py → /api/jobs) ---
// The cockpit refresh buttons. "blocked" is what an UNFORCED start would run into:
// the chain's own day/week marker, or the daily chain's weekday guard.
export interface JobProgress {
  current: string | null;
  current_since: string | null;
  done_count: number;
  expected_total: number;
  failed: string[];
  started_at: string | null;
}

export interface JobState {
  key: string;
  label: string;
  running: boolean;
  blocked: "already_ran" | "weekend" | null;
  last_run: string | null;
  progress: JobProgress;
  tail: string[];
  // Full refresh only: when each of its three phases last ran.
  sub_runs?: Record<string, string | null>;
}

export interface JobsResponse {
  jobs: JobState[];
  disclaimer: string;
}

export async function fetchJobs(): Promise<JobsResponse> {
  // no-store: the service worker's stale-while-revalidate cache would serve a finished
  // run's status while a chain is live, which is the one thing this view must not do.
  const response = await fetch("/api/jobs", { cache: "no-store" });
  if (!response.ok) throw new Error(`/api/jobs returned ${response.status}`);
  return response.json();
}

export interface StartJobResponse {
  started?: boolean;
  forced?: boolean;
  reason?: "already_ran" | "weekend";
  error?: string;
  job?: JobState;
  status: number; // 200 started/blocked · 404 unknown key · 409 a chain holds the lock
}

export async function startJob(key: string, force: boolean): Promise<StartJobResponse> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(key)}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force }),
  });
  const body = (await response.json()) as Omit<StartJobResponse, "status">;
  return { ...body, status: response.status };
}
```

Create `frontend/src/jobs.ts`:

```ts
import type { JobState } from "./api";

/** Whole minutes between an ISO timestamp and now; negative clock skew clamps to 0. */
function minutesSince(iso: string, nowMs: number): number {
  return Math.max(0, Math.round((nowMs - new Date(iso).getTime()) / 60_000));
}

/**
 * One sentence for the panel. "~12" and not "12": the daily chain prepends two Monday
 * steps, so the expected total is a floor, not a promise.
 */
export function describeProgress(job: JobState, nowMs: number): string {
  const { current, current_since, done_count, expected_total, failed, started_at } = job.progress;
  if (!job.running) return "läuft nicht";

  let text: string;
  if (current) {
    const position = done_count + 1;
    text = `Schritt ${position} von ~${expected_total}: ${current}`;
    if (current_since) text += ` · seit ${minutesSince(current_since, nowMs)} Min.`;
  } else if (started_at) {
    text = `läuft seit ${minutesSince(started_at, nowMs)} Min.`;
  } else {
    text = "läuft";
  }
  if (failed.length > 0) {
    const word = failed.length === 1 ? "Schritt" : "Schritte";
    text += ` · ${failed.length} ${word} fehlgeschlagen (${failed.join(", ")})`;
  }
  return text;
}

/** Marker values are either a day ("2026-08-07") or an ISO week ("2026-W32"). */
export function formatMarker(marker: string | null): string {
  if (!marker) return "noch nie";
  const week = /^(\d{4})-W(\d{2})$/.exec(marker);
  if (week) return `KW ${week[2]}/${week[1]}`;
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(marker);
  if (day) return `${day[3]}.${day[2]}.${day[1]}`;
  return marker;
}

export function blockedText(blocked: JobState["blocked"]): string {
  if (blocked === "weekend") {
    return "Heute ist Wochenende — die Tages-Kette läuft planmäßig nicht.";
  }
  if (blocked === "already_ran") {
    return "Ist heute schon gelaufen.";
  }
  return "";
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm test -- jobs && npm run typecheck`
Expected: `jobs.test.ts` 10 passed, typecheck clean.

- [ ] **Step 5: Commit**

```bash
cd ~/private/equity-scout
git add frontend/src/api.ts frontend/src/jobs.ts frontend/src/jobs.test.ts
git commit -m "feat: add job API client and progress helpers to the dashboard"
```

---

### Task 7: The RefreshPanel component

**Files:**
- Create: `frontend/src/components/RefreshPanel.tsx`
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/RefreshPanel.tsx`:

```tsx
import { useCallback, useEffect, useState } from "react";

import { fetchJobs, startJob, type JobState } from "../api";
import { blockedText, describeProgress, formatMarker } from "../jobs";

// While something runs the panel is the only feedback there is, so it polls fast; idle it
// mostly waits. Both are far below the cheapest chain step, so this costs nothing real.
const POLL_RUNNING_MS = 5_000;
const POLL_IDLE_MS = 20_000;

const PHASE_LABELS: Record<string, string> = {
  scout: "Voll-Scout",
  daily: "Tages-Update",
  nightly: "Nachtlauf",
};

const JOB_NOTES: Record<string, string> = {
  daily:
    "Radar, Insights, Earnings, Evidenz, F-Score, Watchlist-Scoring, Auflösungen, Lanes, Digest. Dauert rund 26 Minuten und schickt am Ende den Telegram-Digest.",
  full:
    "Voll-Scout über das ganze Universum, danach Tages-Update, danach Nachtlauf (Training + Depot). Läuft je nach Universum ein bis mehrere Stunden.",
};

function JobCard({
  job,
  now,
  onStarted,
}: {
  job: JobState;
  now: number;
  onStarted: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // Two-tap contract: the first tap on a blocked daily job (or on the hours-long full
  // refresh) only explains; the second one, with force, actually starts.
  const [armed, setArmed] = useState(false);

  const blocked = blockedText(job.blocked);
  // The full refresh IS the explicit "redo everything" button: unforced, each phase whose
  // marker is current would skip silently and the button would look broken.
  const alwaysForce = job.key === "full";

  async function start(force: boolean) {
    setPending(true);
    setMessage(null);
    try {
      const result = await startJob(job.key, force);
      if (result.status === 409) {
        setMessage(result.error ?? "Läuft bereits.");
      } else if (result.started === false) {
        setMessage(`${blockedText(result.reason ?? null)} Mit „Trotzdem starten" erzwingen.`);
        setArmed(true);
      } else if (result.status !== 200) {
        setMessage(result.error ?? `Fehler ${result.status}.`);
      } else {
        setMessage("Gestartet.");
        setArmed(false);
      }
      onStarted();
    } catch (error) {
      setMessage(`Start fehlgeschlagen: ${String(error)}`);
    } finally {
      setPending(false);
    }
  }

  const label = (() => {
    if (job.running) return "Läuft…";
    // The full card never says "Trotzdem" — it is not blocked, it is just expensive, so
    // its two taps read as "Alles neu laden" then "Wirklich alles neu laden".
    if (alwaysForce) return armed ? "Wirklich alles neu laden" : "Alles neu laden";
    if (armed || job.blocked !== null) return "Trotzdem starten";
    return "Jetzt starten";
  })();

  return (
    <section className="refresh-card">
      <header className="refresh-card-head">
        <h3>{job.label}</h3>
        <span className={job.running ? "refresh-state running" : "refresh-state"}>
          {describeProgress(job, now)}
        </span>
      </header>

      <p className="refresh-note">{JOB_NOTES[job.key]}</p>

      {job.sub_runs ? (
        <ul className="refresh-subruns">
          {Object.entries(job.sub_runs).map(([phase, marker]) => (
            <li key={phase}>
              <span>{PHASE_LABELS[phase] ?? phase}</span>
              <span>{formatMarker(marker)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="refresh-last">Zuletzt gelaufen: {formatMarker(job.last_run)}</p>
      )}

      {blocked && !job.running && <p className="refresh-blocked">{blocked}</p>}

      <button
        className="refresh-button"
        disabled={pending || job.running}
        onClick={() => {
          if (alwaysForce && !armed) {
            setArmed(true);
            setMessage("Das lädt alles neu und läuft mehrere Stunden. Nochmal tippen zum Starten.");
            return;
          }
          void start(alwaysForce || armed);
        }}
      >
        {pending ? "…" : label}
      </button>

      {message && <p className="refresh-message">{message}</p>}

      {job.tail.length > 0 && (
        <details className="refresh-log">
          <summary>Log ansehen</summary>
          <pre>{job.tail.join("\n")}</pre>
        </details>
      )}
    </section>
  );
}

/** "Labor → Aktualisieren": start the data chains by hand and watch them run. */
export function RefreshPanel() {
  const [jobs, setJobs] = useState<JobState[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      const response = await fetchJobs();
      setJobs(response.jobs);
      setError(null);
    } catch (e: unknown) {
      setError(String(e));
    }
  }, []);

  const anyRunning = jobs?.some((job) => job.running) ?? false;

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => {
      setNow(Date.now());
      void load();
    }, anyRunning ? POLL_RUNNING_MS : POLL_IDLE_MS);
    return () => window.clearInterval(interval);
  }, [load, anyRunning]);

  if (error) return <p className="error">Status nicht abrufbar: {error}</p>;
  if (jobs === null) return <p className="muted">Lade Status…</p>;

  return (
    <div className="refresh-panel">
      <p className="muted">
        Die Ketten laufen normalerweise nach Zeitplan (Tages-Update werktags 18:00, Nachtlauf
        2:30, Voll-Scout montags 5:30). Hier startest du sie von Hand.
      </p>
      {jobs.map((job) => (
        <JobCard key={job.key} job={job} now={now} onStarted={load} />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Add the styles**

Append to `frontend/src/index.css`:

These are the stylesheet's real token names — `--border`, `--text-muted`, `--accent`, `--warning`, `--bg-surface`, `--bg-inset`. Do not invent `--line`/`--muted`/`--card`; they do not exist in this palette.

```css
/* Cockpit refresh panel (Labor → Aktualisieren, 2026-08-09) */
.refresh-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.refresh-card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.9rem 1rem;
  background: var(--bg-surface);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.refresh-card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.4rem;
}

.refresh-card-head h3 {
  margin: 0;
  font-size: 1rem;
}

.refresh-state {
  font-size: 0.82rem;
  color: var(--text-muted);
}

.refresh-state.running {
  color: var(--accent);
  font-weight: 600;
}

.refresh-note,
.refresh-last,
.refresh-blocked,
.refresh-message {
  margin: 0;
  font-size: 0.85rem;
  color: var(--text-muted);
}

.refresh-blocked {
  color: var(--warning);
}

.refresh-subruns {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 0.85rem;
  color: var(--text-muted);
}

.refresh-subruns li {
  display: flex;
  justify-content: space-between;
  padding: 0.15rem 0;
}

.refresh-button {
  align-self: flex-start;
  min-height: 44px; /* phone tap target */
  padding: 0 1.1rem;
  border-radius: 10px;
  border: 1px solid var(--border-strong);
  background: var(--bg-raised);
  color: inherit;
  font-size: 0.95rem;
  font-weight: 600;
}

.refresh-button:disabled {
  opacity: 0.55;
}

.refresh-log pre {
  max-height: 40vh;
  overflow: auto;
  padding: 0.5rem;
  background: var(--bg-inset);
  border-radius: 8px;
  font-size: 0.72rem;
  line-height: 1.35;
  white-space: pre-wrap;
  word-break: break-word;
}
```

Sanity-check the tokens resolved (a typo renders as an inherited default, not an error):

```bash
grep -cE "var\(--(border|border-strong|text-muted|accent|warning|bg-surface|bg-inset|bg-raised)\)" frontend/src/index.css
```
Expected: a count well above the 12 new usages — these tokens are used throughout the file already.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no output (clean).

- [ ] **Step 4: Commit**

```bash
cd ~/private/equity-scout
git add frontend/src/components/RefreshPanel.tsx frontend/src/index.css
git commit -m "feat: add refresh panel with chain buttons, progress and log tail"
```

---

### Task 8: Wire the panel into Labor

**Files:**
- Modify: `frontend/src/components/LaborView.tsx`, `frontend/src/views.ts`

- [ ] **Step 1: Add the tab**

In `frontend/src/components/LaborView.tsx`:

1. Add the import next to the other component imports:
```tsx
import { RefreshPanel } from "./RefreshPanel";
```

2. Add `"aktualisieren"` as the first member of the `LaborTab` union:
```tsx
type LaborTab =
  | "aktualisieren"
  | "strategien"
  | "modell"
  | "filter"
  | "lernkurven"
  | "screener"
  | "radar"
  | "depots";
```

3. Make it the first entry of `TABS` — the refresh is the one thing here you come to *do*, not to read:
```tsx
const TABS: { key: LaborTab; label: string }[] = [
  { key: "aktualisieren", label: "Aktualisieren" },
  { key: "strategien", label: "Strategien" },
  { key: "modell", label: "Entry-Modell" },
  { key: "filter", label: "Signal-Filter" },
  { key: "lernkurven", label: "Lernkurven" },
  { key: "screener", label: "Screener (Rohdaten)" },
  { key: "radar", label: "Radar (Rohdaten)" },
  { key: "depots", label: "Forschungs-Depots" },
];
```

4. Add the render branch. The component ends with a block of `{tab === "…" && <Comp />}` lines; put the new one first, directly after the `</div>` that closes `<div className="tabbar wrap">`:
```tsx
      {tab === "aktualisieren" && <RefreshPanel />}
      {tab === "strategien" && <StrategyDashboard />}
```

Leave `useState<LaborTab>("strategien")` untouched — which tab opens first is a separate UX decision, and Labor's current default is a reading surface.

- [ ] **Step 2: Mention it in the Mehr sheet**

In `frontend/src/views.ts`, change the Labor note so the entry point is findable from the sheet:

```ts
  labor: "Strategien, Modelle, Lernkurven — und Daten aktualisieren.",
```

- [ ] **Step 3: Verify the build**

Run:
```bash
cd frontend && npm run typecheck && npm test && npm run build
```
Expected: typecheck clean, all vitest files pass, `vite build` writes the bundle without warnings about missing exports.

- [ ] **Step 4: Commit**

```bash
cd ~/private/equity-scout
git add frontend/src/components/LaborView.tsx frontend/src/views.ts
git commit -m "feat: surface the refresh panel as the first Labor tab"
```

---

### Task 9: Full gate — every test, both suites

**Files:** none (verification only)

- [ ] **Step 1: Run the Python suite**

Run: `cd ~/private/equity-scout && .venv/bin/python -m pytest -q`
Expected: everything passes. The suite is ~1750 tests; if anything unrelated fails, check whether it also fails on `git stash` before treating it as your regression.

- [ ] **Step 2: Run ruff over the whole diff**

Run: `.venv/bin/python -m ruff check src/ tests/ scripts/`
Expected: `All checks passed!`

- [ ] **Step 3: Run the frontend suite**

Run: `cd frontend && npm run typecheck && npm test && npm run build`
Expected: clean typecheck, all tests pass, build succeeds.

- [ ] **Step 4: Verify bash syntax of all four wrappers**

Run:
```bash
cd ~/private/equity-scout
for f in scripts/run_daily_guarded.sh scripts/run_nightly_guarded.sh \
         scripts/run_weekly_guarded.sh scripts/run_full_refresh.sh; do
  bash -n "$f" && echo "OK $f"
done
```
Expected: four `OK` lines.

---

### Task 10: Live verification on the running service

**Files:** none (verification only)

**This task changes live state — announce each step to Nico before running it and stop where it says stop.**

- [ ] **Step 1: Rebuild the served frontend and restart the dashboard**

The service serves the built bundle, so a source-only change is invisible until both happen:

```bash
cd ~/private/equity-scout/frontend && npm run build
systemctl --user restart equity-scout-dash.service
systemctl --user is-active equity-scout-dash.service
```
Expected: `active`.

- [ ] **Step 2: Read the status through the real API**

```bash
cd ~/private/equity-scout
TOKEN=$(grep '^DASH_TOKEN=' .env | cut -d= -f2)
curl -s -H "X-Dash-Token: $TOKEN" http://127.0.0.1:8420/api/jobs | .venv/bin/python -m json.tool
```
Expected: two jobs. `daily` shows `"running": false`, `"last_run": "2026-08-07"`, and `"blocked": "weekend"` when run on a Saturday or Sunday. `full` shows `"sub_runs"` with `scout: null` (the weekly marker has never been written).

- [ ] **Step 3: Verify the honest no-op answer**

```bash
curl -s -X POST -H "X-Dash-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"force": false}' http://127.0.0.1:8420/api/jobs/daily/start | .venv/bin/python -m json.tool
```
Expected on a weekend: `"started": false, "reason": "weekend"`. On a weekday where the chain already ran: `"reason": "already_ran"`. Confirm no new systemd unit appeared:
```bash
systemctl --user list-units 'es-job-*' --all
```
Expected: no units listed.

- [ ] **Step 4: STOP — get Nico's go before the forced start**

A forced daily run is not a dry run: it executes `run_notify.py --min-pitches 5` and `run_digest.py`, so **Nico receives Telegram messages**, and it writes to `equity_scout.db` for ~26 minutes. Tell him exactly that and wait for his go.

- [ ] **Step 5: Forced start and progress check**

```bash
curl -s -X POST -H "X-Dash-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"force": true}' http://127.0.0.1:8420/api/jobs/daily/start | .venv/bin/python -m json.tool
systemctl --user list-units 'es-job-*' --all
grep FORCED copilot.log | tail -2
```
Expected: `"started": true, "forced": true`; one `es-job-daily-<epoch>.service` unit; a `guarded: FORCED run (trigger: cockpit)` line in `copilot.log`.

After ~2 minutes:
```bash
curl -s -H "X-Dash-Token: $TOKEN" http://127.0.0.1:8420/api/jobs \
  | .venv/bin/python -c 'import json,sys; j=json.load(sys.stdin)["jobs"][0]; print(j["running"], j["progress"])'
```
Expected: `True` plus a `current` step name and a rising `done_count`.

- [ ] **Step 6: Prove the run survives a service restart**

This is the whole reason for `systemd-run`:

```bash
systemctl --user restart equity-scout-dash.service
sleep 5
systemctl --user list-units 'es-job-*' --all
curl -s -H "X-Dash-Token: $TOKEN" http://127.0.0.1:8420/api/jobs \
  | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["jobs"][0]["running"])'
```
Expected: the `es-job-daily-*` unit is still active and `running` is still `True`.

- [ ] **Step 7: Verify the lock refusal against the live run**

While the chain is still running:
```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H "X-Dash-Token: $TOKEN" \
  -H "Content-Type: application/json" -d '{"force": true}' \
  http://127.0.0.1:8420/api/jobs/daily/start
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H "X-Dash-Token: $TOKEN" \
  -H "Content-Type: application/json" -d '{"force": true}' \
  http://127.0.0.1:8420/api/jobs/full/start
```
Expected: **409** both times — force never bypasses the lock, and the running daily chain blocks the full refresh too.

- [ ] **Step 8: Phone check**

Ask Nico to open the cockpit on his phone (Tailscale), go Mehr → Labor → Aktualisieren, and confirm: both cards render, the running chain shows a step name that advances, "Log ansehen" opens the tail, and the button is disabled while it runs.

- [ ] **Step 9: Confirm the chain finished cleanly**

```bash
grep "guarded: chain finished" copilot.log | tail -1
cat .state/daily_last_run
```
Expected: `rc=0` and today's date in the marker.

---

### Task 11: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-09-cockpit-refresh-buttons.md` (this file)

- [ ] **Step 1: Document the buttons in the README**

Find the "Handy-Cockpit" section (`grep -n "Handy-Cockpit" README.md`) and add, in that section's style and language:

```markdown
### Aktualisieren von Hand (Mehr → Labor → Aktualisieren)

Zwei Buttons starten die Datenketten außerhalb des Zeitplans:

- **Tages-Update** — `scripts/run_daily_guarded.sh` (~26 min, endet mit dem Telegram-Digest).
- **Alles aktualisieren** — `scripts/run_full_refresh.sh`: Voll-Scout → Tages-Update → Nachtlauf, mehrere Stunden.

Beide laufen als eigene transiente systemd-Unit (`es-job-<key>-<epoch>.service`), damit ein
Neustart des Dashboards eine laufende Kette nicht mitreißt. Der erste Tap meldet nur, wenn
die Kette heute schon gelaufen ist oder der Wochenend-Guard greift; erst ein zweiter,
expliziter Tap setzt `EQUITY_SCOUT_FORCE=1` und umgeht Marker und Wochenend-Guard. Den
flock umgeht nichts — zwei Ketten auf einer SQLite-Datei bleiben ausgeschlossen.
```

- [ ] **Step 2: Append the outcome section to this plan**

Add at the end of this file: what was implemented, any deviation from the plan, measured runtimes from Task 10, and whatever stayed open (e.g. whether Nico wants the entry point somewhere more prominent than Labor).

- [ ] **Step 3: Commit**

```bash
git add README.md docs/superpowers/plans/2026-08-09-cockpit-refresh-buttons.md
git commit -m "docs: document the cockpit refresh buttons"
```

---

## Outcome (2026-08-09)

Implemented in full on `autopilot/work`, seven commits, `f375c91` … `6cf8234`. Gate:
**1833 pytest passed**, `ruff check src/ tests/ scripts/` clean, **121 vitest passed**,
`tsc --noEmit` clean, `bash -n` clean on all four wrappers.

**One deviation from the plan, and it is load-bearing.** Task 3's test caught that the
guarded wrappers ended on an `if/else` and therefore *always* exited 0 — a chain that
genuinely failed was indistinguishable from one that succeeded. `run_full_refresh.sh`
would have logged a rate-limited full scout as `OK scout`, and the cockpit would have
shown a green phase it never got. All three wrappers now end in `exit "$rc"`, so a chain
that actually ran reports its own result; a marker or weekend skip still exits 0. This
touches scheduler infrastructure the plan had meant to leave alone, so it is deliberate
and tested (`test_failed_chain_propagates_its_exit_code`, `test_a_quiet_skip_still_exits_zero`
in both the daily and weekly wrapper tests). The parallel P3 session was notified and
confirmed it does not affect its work.

**Second, smaller deviation:** `api.py` could not take a `from datetime import date`
import — a loop variable named `date` further up the file shadows it (ruff F402, and that
lint failure briefly blocked the shared gate for the two parallel sessions in this tree).
The route uses `datetime.now().date()` instead.

**Live verification, measured against the running service:**

| check | result |
|---|---|
| `GET /api/jobs` | daily `blocked: "weekend"`, `last_run: 2026-08-07`, 12/12 steps parsed from the real log; full `sub_runs.scout: null` |
| unforced `POST daily/start` | `started: false, reason: "weekend"`, **no** systemd unit created |
| unknown job key | 404, nothing launched |
| forced `POST daily/start` | `started: true, forced: true`, unit `es-job-daily-1786305671.service` active, `guarded: FORCED run (trigger: cockpit)` in `copilot.log` |
| **dashboard restart mid-run** | unit still active, progress unchanged (`current: insights`) — the whole reason for `systemd-run` |
| second `POST daily/start` with force | **409** |
| `POST full/start` with force while daily runs | **409**, `Läuft bereits (.state/daily.lock).` |
| token gate | 401 on both routes without a token (`tests/test_api_auth.py` + manual TestClient check) |

**Known cosmetic side effect:** seven `guarded: weekend trigger (test)` lines landed in the
real `copilot.log` at 21:48 — they come from the TDD red run in Task 1, executed before the
`EQUITY_SCOUT_DAILY_LOG` seam existed, when the wrapper still wrote to the repo log
unconditionally. Harmless (they are not session markers, so `parse_progress` ignores them)
and self-healing: the next real run's session line moves the tail past them.

**Not done:** the README section. `README.md` belongs to the parallel P2 session in this
working tree right now; the documentation lives in this plan until that session lands, then
the "Aktualisieren von Hand" block from Task 11 can be added.

## Open points for Nico

- **Where the entry point lives.** The panel sits in Labor (Mehr → Labor → Aktualisieren), two taps from the start screen. That keeps the Heute tab clean, but if you want it on Heute instead, that is a one-line change in `TodayView.tsx` — say so and it moves.
- **The nightly chain has no button of its own.** It is 2.5 minutes and part of "Alles aktualisieren"; a third button felt like clutter. Trivial to add if you want it standalone.
- **The full refresh always forces.** Deliberate (see the header). It means a full refresh re-runs phases that already ran today — that is the point of the button, but it also means it is the expensive one.
