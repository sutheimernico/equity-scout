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


def test_trading_horizon_stamps_later_than_a_calendar_horizon(tmp_path):
    """63 trading days are ~93 calendar days: `due` must mean MEASURABLE (Wave-1 lesson)."""
    from datetime import datetime, timedelta

    from equity_scout.evidence.ledger import HORIZON_UNIT_TRADING

    db = str(tmp_path / "ev.db")
    log_evidence(db, [_event(key="cal")], now=NOW, horizon_days=63)
    log_evidence(
        db, [_event(key="trd")], now=NOW, horizon_days=63, horizon_unit=HORIZON_UNIT_TRADING
    )
    stamps = {
        row["event_key"]: row["resolve_after"]
        for row in due_evidence(db, "2030-01-01T00:00:00+00:00")
    }
    assert datetime.fromisoformat(stamps["cal"]) - datetime.fromisoformat(NOW) == timedelta(
        days=63
    )
    assert datetime.fromisoformat(stamps["trd"]) - datetime.fromisoformat(NOW) == timedelta(
        days=93
    )


def test_unknown_horizon_unit_is_refused(tmp_path):
    db = str(tmp_path / "ev.db")
    with pytest.raises(ValueError, match="horizon_unit"):
        log_evidence(db, [_event()], now=NOW, horizon_days=10, horizon_unit="fortnights")


def test_open_tickers_are_scoped_to_one_source(tmp_path):
    from equity_scout.evidence.ledger import open_tickers

    db = str(tmp_path / "ev.db")
    log_evidence(db, [_event(ticker="AAA", key="a")], now=NOW, horizon_days=1)
    log_evidence(
        db, [_event(source=SOURCE_NEWS_THEME, ticker="BBB", key="b")], now=NOW, horizon_days=1
    )
    assert open_tickers(db, source=SOURCE_CONGRESS) == {"AAA"}
    assert open_tickers(db, source=SOURCE_NEWS_THEME) == {"BBB"}

    row_id = due_evidence(db, "2026-07-20T00:00:00+00:00")[0]["id"]
    resolve_evidence(
        db, row_id, realized_relative_return=0.01, resolved_at="2026-07-20T00:00:00+00:00"
    )
    assert open_tickers(db, source=SOURCE_CONGRESS) == set()  # resolved rows are not open


def test_resolved_returns_are_raw_and_ordered(tmp_path):
    """stats_by_source reports the mean; a shadow track also needs its stderr, so the
    caller must be able to see the individual returns."""
    from equity_scout.evidence.ledger import resolved_returns

    db = str(tmp_path / "ev.db")
    log_evidence(db, [_event(key="a"), _event(key="b")], now=NOW, horizon_days=1)
    for row, value in zip(due_evidence(db, "2026-07-20T00:00:00+00:00"), (0.05, -0.01)):
        resolve_evidence(
            db, row["id"], realized_relative_return=value,
            resolved_at="2026-07-20T00:00:00+00:00",
        )
    assert resolved_returns(db, source=SOURCE_CONGRESS) == [0.05, -0.01]
    assert resolved_returns(db, source=SOURCE_NEWS_THEME) == []
