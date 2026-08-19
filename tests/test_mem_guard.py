"""Memory guard: caps a heavy chain so a runaway job dies alone instead of with the VM."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[1]
GUARD = REPO_DIR / "scripts" / "mem_guard.sh"

has_systemd_run = shutil.which("systemd-run") is not None


def _run(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ, **(env_extra or {}))
    return subprocess.run(
        ["bash", str(GUARD), *args], env=env, capture_output=True, text=True, timeout=60
    )


def _script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "job.sh"
    script.write_text(f"#!/usr/bin/env bash\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_runs_the_command_and_passes_stdout_through(tmp_path) -> None:
    result = _run(str(_script(tmp_path, "echo hello-from-chain")))
    assert result.returncode == 0
    assert "hello-from-chain" in result.stdout


def test_passes_the_exit_code_through(tmp_path) -> None:
    # The nightly wrapper logs rc= from this, so a swallowed failure would read as success.
    assert _run(str(_script(tmp_path, "exit 3"))).returncode == 3


def test_no_command_is_a_usage_error() -> None:
    assert _run().returncode == 2


def test_bypass_switch_still_runs_the_command(tmp_path) -> None:
    log = tmp_path / "guard.log"
    result = _run(
        str(_script(tmp_path, "echo ran")),
        env_extra={
            "EQUITY_SCOUT_MEM_GUARD": "off",
            "EQUITY_SCOUT_MEM_GUARD_LOG": str(log),
        },
    )
    assert result.returncode == 0
    assert "ran" in result.stdout
    assert "bypass" in log.read_text()


def test_raises_the_oom_preference_so_interactive_sessions_are_spared(tmp_path) -> None:
    result = _run(str(_script(tmp_path, "cat /proc/self/oom_score_adj")))
    assert result.stdout.strip() == "500"


@pytest.mark.skipif(not has_systemd_run, reason="systemd-run unavailable")
def test_the_ceilings_actually_reach_the_cgroup(tmp_path) -> None:
    # The point of the whole script: without this assertion it could silently run uncapped.
    reader = _script(
        tmp_path,
        'cg=$(awk -F: "/0::/{print \\$3}" /proc/self/cgroup)\n'
        'cat "/sys/fs/cgroup$cg/memory.high" "/sys/fs/cgroup$cg/memory.max"',
    )
    log = tmp_path / "guard.log"
    result = _run(
        str(reader),
        env_extra={
            "EQUITY_SCOUT_MEM_HIGH": "1G",
            "EQUITY_SCOUT_MEM_MAX": "2G",
            "EQUITY_SCOUT_MEM_GUARD_LOG": str(log),
        },
    )
    if "uncapped" in log.read_text():
        pytest.skip("no user bus in this environment — guard degraded open as designed")
    assert result.stdout.split() == [str(1024**3), str(2 * 1024**3)]


@pytest.mark.skipif(not has_systemd_run, reason="systemd-run unavailable")
def test_default_ceilings_stay_below_the_vms_own_ram(tmp_path) -> None:
    # A ceiling above MemTotal guards nothing: that is exactly how the 2026-08-19 OOM got
    # through. Derived defaults must always land strictly under the VM's cap.
    mem_total_kb = int(
        next(l for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemTotal:")).split()[1]
    )
    reader = _script(
        tmp_path,
        'cg=$(awk -F: "/0::/{print \\$3}" /proc/self/cgroup)\n'
        'cat "/sys/fs/cgroup$cg/memory.high" "/sys/fs/cgroup$cg/memory.max"',
    )
    log = tmp_path / "guard.log"
    result = _run(str(reader), env_extra={"EQUITY_SCOUT_MEM_GUARD_LOG": str(log)})
    if "uncapped" in log.read_text():
        pytest.skip("no user bus in this environment — guard degraded open as designed")
    high, hard = (int(v) for v in result.stdout.split())
    assert 0 < high < hard < mem_total_kb * 1024
