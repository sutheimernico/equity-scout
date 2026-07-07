"""Evidence ledger: append-only, idempotent logging, guarded resolution, per-source stats."""
from __future__ import annotations

import pytest

from equity_scout.evidence.base import SOURCE_CONGRESS, SOURCE_NEWS_THEME, EvidenceEvent
from equity_scout.evidence.ledger import (
    due_evidence,
    log_evidence,
    resolve_evidence,
    stats_by_source,
)

NOW = "2026-07-07T12:00:00+00:00"


def _event(source: str = SOURCE_CONGRESS, ticker: str = "NVDA", key: str = "k1") -> EvidenceEvent:
    return EvidenceEvent(
        source=source, ticker=ticker, event_key=key, event_date="2026-06-20", details={}
    )


def test_log_evidence_is_idempotent_per_event(tmp_path):
    db = str(tmp_path / "test.db")
    assert log_evidence(db, [_event()], now=NOW) == 1
    assert log_evidence(db, [_event()], now=NOW) == 0  # same fact never inflates the sample
    assert log_evidence(db, [_event(key="k2")], now=NOW) == 1


def test_due_evidence_respects_horizon(tmp_path):
    db = str(tmp_path / "test.db")
    log_evidence(db, [_event()], now=NOW, horizon_days=60)
    assert due_evidence(db, "2026-08-01T00:00:00+00:00") == []  # 25 days: not due
    due = due_evidence(db, "2026-09-10T00:00:00+00:00")  # 65 days: due
    assert [d["ticker"] for d in due] == ["NVDA"]
    assert due[0]["source"] == SOURCE_CONGRESS


def test_resolution_is_single_transition(tmp_path):
    db = str(tmp_path / "test.db")
    log_evidence(db, [_event()], now=NOW, horizon_days=1)
    row_id = due_evidence(db, "2026-07-09T00:00:00+00:00")[0]["id"]

    assert resolve_evidence(
        db, row_id, realized_relative_return=0.04, resolved_at="2026-07-09T00:00:00+00:00"
    )
    # A second attempt is refused; the first resolution stands.
    assert not resolve_evidence(
        db, row_id, realized_relative_return=-0.9, resolved_at="2026-07-10T00:00:00+00:00"
    )
    stats = stats_by_source(db)[SOURCE_CONGRESS]
    assert stats["n_resolved"] == 1
    assert stats["mean_relative_return"] == 0.04

    with pytest.raises(ValueError):
        resolve_evidence(db, 999, realized_relative_return=0.0, resolved_at=NOW)


def test_stats_by_source_splits_sources_and_open_rows(tmp_path):
    db = str(tmp_path / "test.db")
    log_evidence(
        db,
        [_event(), _event(key="k2"), _event(source=SOURCE_NEWS_THEME, ticker="XOM", key="t1")],
        now=NOW,
        horizon_days=1,
    )
    later = "2026-07-09T00:00:00+00:00"
    first, second = due_evidence(db, later)[:2]
    resolve_evidence(db, first["id"], realized_relative_return=0.02, resolved_at=later)
    resolve_evidence(db, second["id"], realized_relative_return=-0.01, resolved_at=later)

    stats = stats_by_source(db)
    assert stats[SOURCE_CONGRESS]["n_resolved"] == 2
    assert stats[SOURCE_CONGRESS]["hit_rate"] == 0.5
    assert stats[SOURCE_NEWS_THEME] == {
        "n_resolved": 0, "n_open": 1, "hit_rate": None, "mean_relative_return": None,
    }
