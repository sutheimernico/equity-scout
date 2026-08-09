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
        label="Alles neu laden",
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

    session = _SESSION_RE.match(lines[start_idx])
    started_at = session.group("ts") if session else None
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


def build_start_command(spec: JobSpec, root: Path, *, force: bool, unit_suffix: str) -> list[str]:
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
