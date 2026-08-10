"""A hanging chain step must not eat the whole task budget (found live 2026-08-10).

`insights` (normally 2-3 min) crawled under heavy CPU load; the Windows Task Scheduler killed
the daily chain at its 1-hour limit with 0xC000013A, and everything after it — evidence,
fscore, the resolvers and NOTIFY — never ran. No log line, no day marker: the day's delivery
was lost silently because of a cosmetic step. These tests run the real scripts with a fake
chain command, so they pin the behaviour rather than the wording.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[1]
CHAINS = ("daily_copilot.sh", "nightly_train.sh")


@pytest.mark.parametrize("chain", CHAINS)
def test_every_step_runs_under_a_wall_clock_cap(chain: str) -> None:
    text = (REPO_DIR / "scripts" / chain).read_text()
    assert 'timeout "$STEP_TIMEOUT"' in text, chain
    # Overridable per run, with a default — a hard-coded cap could not be widened for a
    # legitimately slow one-off (a full refresh, a first training run on a cold panel).
    assert 'STEP_TIMEOUT="${EQUITY_SCOUT_STEP_TIMEOUT:-' in text, chain


@pytest.mark.parametrize("chain", CHAINS)
def test_a_timeout_is_logged_as_a_timeout_and_the_chain_continues(chain: str, tmp_path) -> None:
    """The distinction matters: "too slow" and "broken" need different fixes, and the old
    code could report neither because the step simply never returned."""
    script = REPO_DIR / "scripts" / chain
    log = tmp_path / "chain.log"
    # A 1-second cap plus a step that sleeps longer: the cap must fire, be named as a
    # TIMEOUT, and the script must still reach its own end marker.
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "EQUITY_SCOUT_STEP_TIMEOUT": "1s",
    }
    body = f"""
    set -u
    LOG="{log}"
    STEP_TIMEOUT="${{EQUITY_SCOUT_STEP_TIMEOUT:-12m}}"
    {_step_function(script)}
    step slow_step /bin/sleep 30
    step fast_step /bin/true
    echo "[end] reached" >> "$LOG"
    """
    subprocess.run(["/bin/bash", "-c", body], env=env, check=True, timeout=60)
    text = log.read_text()
    assert "TIMEOUT slow_step" in text
    assert "OK fast_step" in text  # the chain carried on past the hanging step
    assert "reached" in text


def _step_function(script: Path) -> str:
    """Lift the real `step()` definition out of the chain script, so the test exercises the
    shipped implementation instead of a copy that could drift away from it."""
    text = script.read_text()
    start = text.index("step() {")
    end = text.index("\n}\n", start) + len("\n}\n")
    return text[start:end]
