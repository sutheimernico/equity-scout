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


def _stub(tmp_path: Path, name: str, *, exit_code: int = 0) -> Path:
    """A chain stub that records its own name in a shared order file, then exits."""
    order = tmp_path / "order"
    script = tmp_path / f"{name}.sh"
    if exit_code == 0:
        script.write_text(f"#!/usr/bin/env bash\necho {name} >> {order}\nexit 0\n")
    else:
        # A failing phase records nothing: the order file then proves the wrapper
        # carried on to the phases behind it.
        script.write_text(f"#!/usr/bin/env bash\nexit {exit_code}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _run(tmp_path: Path, *, failing: str | None = None) -> subprocess.CompletedProcess:
    """Runs the wrapper with all three chains stubbed. `failing` names the phase that exits 4.

    Always forced: that is how the cockpit invokes it, and the sub-markers from an earlier
    run inside the same tmp_path must not arbitrate a second run away.
    """
    state = tmp_path / "state"

    def stub(name: str) -> str:
        return str(_stub(tmp_path, name, exit_code=4 if failing == name else 0))

    env = dict(
        os.environ,
        EQUITY_SCOUT_FORCE="1",
        EQUITY_SCOUT_FULL_LOG=str(tmp_path / "full_refresh.log"),
        EQUITY_SCOUT_FULL_STATE=str(state),
        EQUITY_SCOUT_WEEKLY_CHAIN=stub("scout"),
        EQUITY_SCOUT_WEEKLY_STATE=str(state),
        EQUITY_SCOUT_WEEKLY_LOG=str(tmp_path / "scout_full.log"),
        EQUITY_SCOUT_CHAIN=stub("daily"),
        EQUITY_SCOUT_DAILY_STATE=str(state),
        EQUITY_SCOUT_DAILY_LOG=str(tmp_path / "copilot.log"),
        EQUITY_SCOUT_NIGHTLY_CHAIN=stub("nightly"),
        EQUITY_SCOUT_NIGHTLY_STATE=str(state),
        EQUITY_SCOUT_NIGHTLY_LOG=str(tmp_path / "train.log"),
    )
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
    result = _run(tmp_path, failing="scout")
    assert result.returncode == 0
    order = (tmp_path / "order").read_text().split()
    assert order == ["daily", "nightly"]  # scout failed, the chain kept going
    assert "FAILED scout" in (tmp_path / "full_refresh.log").read_text()
