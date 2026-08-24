"""Nightly chain cadence: the entry trainer runs weekly, everything else nightly.

Measured 2026-08-24 over the ledger's whole history: 244 models trained since 2026-07-05,
zero promotions, and the best OOS AUC has sat between 0.5069 and 0.5074 for six consecutive
runs against a promotion gate of 0.55. The nightly retrain costs ~15 minutes of a 25-minute
step cap (`nightly_train.sh`'s own note) to reproduce a settled null result. Nico's decision
2026-08-24: weekly.

The learning-curve snapshot stays NIGHTLY on purpose — it measures the resolved live
predictions, not the model, so it has something new to say on nights the trainer is silent.
"""
from __future__ import annotations

from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
CHAIN = REPO_DIR / "scripts" / "nightly_train.sh"


def _text() -> str:
    return CHAIN.read_text()


def test_the_entry_trainer_sits_behind_a_weekday_gate() -> None:
    """A `step train_entry` line with no condition in front of it is the nightly cadence
    coming back by accident — the exact regression this test exists to catch."""
    text = _text()
    trainer = text.index("step train_entry")
    gate = text.index("date +%u")
    assert gate < trainer, "train_entry must be inside the weekday gate, not before it"


def test_the_gate_names_saturday() -> None:
    """Saturday 02:30 local is the slot that sees Friday's close — the freshest full week."""
    assert 'TRAIN_ENTRY_DAY="${EQUITY_SCOUT_TRAIN_ENTRY_DAY:-6}"' in _text()


def test_the_trainer_can_be_forced_for_a_manual_run() -> None:
    """Without an override, testing a training change means waiting for Saturday."""
    assert "EQUITY_SCOUT_FORCE_TRAIN" in _text()


def test_the_learning_snapshot_stays_nightly() -> None:
    """It reads resolved predictions, not the model: gating it would throw away six of every
    seven points on the learning curve for nothing."""
    text = _text()
    snapshot_line = next(ln for ln in text.splitlines() if "step learning_snapshot" in ln)
    assert snapshot_line.strip().startswith("step "), snapshot_line


def test_every_other_heavy_step_stays_nightly() -> None:
    """The research batch, the strategy search, the forward accounts, the lanes and the depot
    all have something new to do every night — only the entry trainer does not."""
    text = _text()
    for step in ("step research_batch", "step strategy_research", "step forward_paper",
                 "step st_swing", "step autotrader"):
        line = next(ln for ln in text.splitlines() if step in ln)
        assert line.strip().startswith("step "), line
