"""Weekly guard wrapper: runs once per ISO week, marker blocks re-runs, failed chain retries."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
WRAPPER = REPO_DIR / "scripts" / "run_weekly_guarded.sh"


def _run(tmp_path: Path, chain: Path) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        EQUITY_SCOUT_WEEKLY_CHAIN=str(chain),
        EQUITY_SCOUT_WEEKLY_STATE=str(tmp_path / "state"),
        EQUITY_SCOUT_WEEKLY_LOG=str(tmp_path / "scout_full.log"),
    )
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


def test_runs_the_chain_and_marks_the_week(tmp_path) -> None:
    chain = _chain(tmp_path)
    result = _run(tmp_path, chain)
    assert result.returncode == 0
    assert _runs(tmp_path) == 1
    marker = tmp_path / "state" / "weekly_last_run"
    # ISO year-week, e.g. "2026-W32" — the pair keeps the year boundary unambiguous.
    assert marker.read_text().strip().count("-W") == 1


def test_second_trigger_in_the_same_week_is_a_quiet_skip(tmp_path) -> None:
    chain = _chain(tmp_path)
    _run(tmp_path, chain)
    result = _run(tmp_path, chain)
    assert result.returncode == 0
    assert _runs(tmp_path) == 1  # marker arbitrated the redundant trigger away


def test_failed_chain_leaves_the_week_unmarked_for_retry(tmp_path) -> None:
    failing = _chain(tmp_path, exit_code=3)
    _run(tmp_path, failing)
    marker = tmp_path / "state" / "weekly_last_run"
    assert not marker.exists()
    log = (tmp_path / "scout_full.log").read_text()
    assert "FAILED" in log and "NOT marked" in log
    # the next trigger retries — this time the chain succeeds
    ok = _chain(tmp_path)
    _run(tmp_path, ok)
    assert marker.exists()
