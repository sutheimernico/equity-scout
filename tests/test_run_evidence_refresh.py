"""Refresh-runner tests: the resolve loop is the clock, the registry gate is the judge."""
from __future__ import annotations

import sys
from collections.abc import Callable

from equity_scout.ml.evidence_features import EvidenceIndex
from equity_scout.ml.prediction_ledger import (
    due_predictions,
    log_predictions,
    resolve_prediction,
)
from equity_scout.state_storage import get_state, set_state
from scripts.run_evidence_refresh import (
    DEFAULT_MIN_NEW_RESOLUTIONS,
    MULTIPLICITY_NOTE,
    WATERMARK_KEY,
    main,
    run_evidence_refresh,
)

NOW = "2026-01-01T00:00:00+00:00"
LATER = "2026-03-01T00:00:00+00:00"
EMPTY = EvidenceIndex({})


def _seed_resolved(db: str, n: int) -> None:
    """`n` RESOLVED predictions — the only clock the runner reads."""
    scored = [(f"T{i:04d}", 60, {}) for i in range(n)]
    log_predictions(db, model_version=1, scored=scored, now=NOW, horizon_days=20)
    for pred in due_predictions(db, LATER):
        resolve_prediction(db, pred["id"], realized_relative_return=0.01, resolved_at=LATER)


def _train_spy(calls: list) -> Callable[[EvidenceIndex], list[dict]]:
    def _train(index: EvidenceIndex) -> list[dict]:
        calls.append(index)
        return [
            {"version": 7, "metrics": {}, "promoted": False},
            {"version": 8, "metrics": {}, "promoted": True},
        ]

    return _train


def test_below_the_minimum_nothing_is_re_evaluated(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_resolved(db, DEFAULT_MIN_NEW_RESOLUTIONS - 1)
    calls: list = []
    result = run_evidence_refresh(
        db, apply=True, train=_train_spy(calls), load_index=lambda _: EMPTY
    )
    assert result["triggered"] is False
    assert result["new_resolutions"] == DEFAULT_MIN_NEW_RESOLUTIONS - 1
    assert calls == []  # no trial spent
    assert get_state(db, key=WATERMARK_KEY) is None  # watermark untouched


def test_dry_run_triggers_but_writes_nothing(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_resolved(db, DEFAULT_MIN_NEW_RESOLUTIONS)
    calls: list = []
    result = run_evidence_refresh(
        db, apply=False, train=_train_spy(calls), load_index=lambda _: EMPTY
    )
    assert result["triggered"] is True
    assert result["applied"] is False
    assert calls == []
    assert get_state(db, key=WATERMARK_KEY) is None


def test_apply_trains_reports_the_gate_verdict_and_advances_the_watermark(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_resolved(db, DEFAULT_MIN_NEW_RESOLUTIONS + 5)
    calls: list = []
    result = run_evidence_refresh(
        db, apply=True, train=_train_spy(calls), load_index=lambda _: EMPTY
    )
    assert result["applied"] is True
    assert len(calls) == 1
    assert result["n_candidates"] == 2
    assert result["promoted"] == [8]
    assert get_state(db, key=WATERMARK_KEY) == str(DEFAULT_MIN_NEW_RESOLUTIONS + 5)


def test_a_second_run_without_new_resolutions_refuses(tmp_path):
    """The watermark is what makes this a trigger and not a nightly noise generator."""
    db = str(tmp_path / "es.db")
    _seed_resolved(db, DEFAULT_MIN_NEW_RESOLUTIONS)
    calls: list = []
    run_evidence_refresh(db, apply=True, train=_train_spy(calls), load_index=lambda _: EMPTY)
    second = run_evidence_refresh(
        db, apply=True, train=_train_spy(calls), load_index=lambda _: EMPTY
    )
    assert second["new_resolutions"] == 0
    assert second["triggered"] is False
    assert len(calls) == 1


def test_corrupt_watermark_re_triggers_instead_of_blocking(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_resolved(db, DEFAULT_MIN_NEW_RESOLUTIONS)
    set_state(db, key=WATERMARK_KEY, value="not-a-number")
    result = run_evidence_refresh(
        db, apply=False, train=_train_spy([]), load_index=lambda _: EMPTY
    )
    assert result["watermark"] == 0
    assert result["triggered"] is True


def test_cli_prints_the_refusal_and_the_multiplicity_note(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "es.db")
    _seed_resolved(db, 1)
    monkeypatch.setattr(sys, "argv", ["run_evidence_refresh.py", "--db", db])
    assert main() == 0
    out = capsys.readouterr().out
    assert "Kein Refresh" in out
    assert MULTIPLICITY_NOTE in out
    assert "belegbar" not in out  # honesty guardrail: a gate is never a proof
