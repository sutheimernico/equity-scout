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
    weekday = subprocess.run(["date", "+%u"], capture_output=True, text=True, check=True)
    return int(weekday.stdout.strip()) > 5


def test_forced_run_ignores_the_day_marker(tmp_path) -> None:
    chain = _chain(tmp_path)
    _run(tmp_path, chain, force=True)
    _run(tmp_path, chain, force=True)
    assert _runs(tmp_path) == 2  # marker did not arbitrate the second, explicit run away


def test_unforced_second_run_on_the_same_day_is_a_quiet_skip(tmp_path) -> None:
    chain = _chain(tmp_path)
    if _is_weekend():
        # On a weekend the FIRST unforced run is already skipped, so seed the marker
        # with a forced run and assert the unforced one adds nothing.
        _run(tmp_path, chain, force=True)
        before = _runs(tmp_path)
        _run(tmp_path, chain)
        assert _runs(tmp_path) == before
        return
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
