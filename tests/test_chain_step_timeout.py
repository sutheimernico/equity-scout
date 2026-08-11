"""A hanging chain step must not eat the whole task budget (found live 2026-08-10).

`insights` (normally 2-3 min) crawled under heavy CPU load; the Windows Task Scheduler killed
the daily chain at its 1-hour limit with 0xC000013A, and everything after it — evidence,
fscore, the resolvers and NOTIFY — never ran. No log line, no day marker: the day's delivery
was lost silently because of a cosmetic step. These tests run the real scripts with a fake
chain command, so they pin the behaviour rather than the wording.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[1]
# intraday joined 2026-08-11 after 226 logged runs showed a 995s radar outlier overrunning
# the 15-minute cadence, which made flock skip the next slot too.
CHAINS = ("daily_copilot.sh", "nightly_train.sh", "intraday_copilot.sh")


@pytest.mark.parametrize("chain", CHAINS)
def test_every_step_runs_under_a_wall_clock_cap(chain: str) -> None:
    text = (REPO_DIR / "scripts" / chain).read_text()
    assert 'timeout "$STEP_TIMEOUT"' in text, chain
    # Overridable per run, with a default — a hard-coded cap could not be widened for a
    # legitimately slow one-off (a full refresh, a first training run on a cold panel). Each
    # chain names its OWN variable, because the right cap follows the cadence: 15 minutes of
    # intraday cannot carry the nightly's 25.
    assert re.search(r'STEP_TIMEOUT="\$\{EQUITY_SCOUT_\w*STEP_TIMEOUT:-', text), chain


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


def test_the_session_lane_is_capped_below_its_own_cadence():
    """The per-minute lane is the one place where the lock makes a hang worse than a crash: while
    one run holds `flock -n`, every following minute is SKIPPED, so a stuck network call takes the
    lane silently offline for as long as the process lives. The cap must be under a minute so the
    worst case costs one round."""
    text = (REPO_DIR / "scripts" / "session_lane.sh").read_text()
    match = re.search(r'timeout "\$\{EQUITY_SCOUT_SESSION_TIMEOUT:-(\d+)s\}"', text)
    assert match, "session_lane.sh must cap its run"
    assert int(match.group(1)) < 60, "a cap at or above the 1-minute cadence would not bound it"


def test_full_refresh_is_deliberately_uncapped():
    """Documented decision, not an oversight: run_full_refresh.sh's steps are themselves guarded
    chains (daily 12m, nightly 25m per step), so a cap here would have to span hours and would
    rescue nothing. Pinned so a future reader does not "fix" it by adding one."""
    text = (REPO_DIR / "scripts" / "run_full_refresh.sh").read_text()
    assert 'timeout "$STEP_TIMEOUT"' not in text
    assert "guarded" in text  # the reason: every phase brings its own arbitration
