"""Nightly chain step order: arena lanes must book today's close before the Auto-Depot
reads their equity series as sleeve prices (v13 R1) — see nightly_train.sh's comment for
why this order is load-bearing."""
from __future__ import annotations

from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
CHAIN = REPO_DIR / "scripts" / "nightly_train.sh"


def _text() -> str:
    return CHAIN.read_text()


def test_st_swing_lane_runs_before_the_depot():
    text = _text()
    assert text.index("step st_swing") < text.index("step autotrader")


def test_st_session_sweep_lane_runs_before_the_depot():
    text = _text()
    assert text.index("step st_session_sweep") < text.index("step autotrader")
