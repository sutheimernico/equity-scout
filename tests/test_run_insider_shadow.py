"""Insider shadow lane runner: registers pre-registered predictions, never trades."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from equity_scout.evidence.base import SOURCE_INSIDER, SOURCE_INSIDER_SHADOW, EvidenceEvent
from equity_scout.evidence.ledger import stats_by_source
from equity_scout.evidence.storage import record_events
from scripts.run_insider_shadow import main, run_insider_shadow

NOW = "2026-08-10T18:45:00+00:00"
ENV = {"EDGAR_USER_AGENT": "Nico Sutheimer (nico@example.com)"}


def _seed_cluster(db: str, ticker: str = "AAA", n: int = 3) -> None:
    record_events(
        db,
        [
            EvidenceEvent(
                source=SOURCE_INSIDER,
                ticker=ticker,
                event_key=f"acc{i}-{ticker}",
                event_date=f"2026-08-0{i + 1}",
                details={"insider": f"Insider {i}", "filing_date": f"2026-08-0{i + 1}"},
            )
            for i in range(n)
        ],
        now=NOW,
    )


def _seed_cluster_today(db: str, ticker: str = "AAA", n: int = 3) -> None:
    """`main()` reads the wall clock, so its fixtures must be dated RELATIVE to today —
    hard-coded dates would silently fall out of the 30-day window and turn this into a
    test that starts failing on a calendar date."""
    today = datetime.now(timezone.utc)
    days = [(today - timedelta(days=i + 1)).date().isoformat() for i in range(n)]
    record_events(
        db,
        [
            EvidenceEvent(
                source=SOURCE_INSIDER,
                ticker=ticker,
                event_key=f"acc{i}-{ticker}",
                event_date=days[i],
                details={"insider": f"Insider {i}", "filing_date": days[i]},
            )
            for i in range(n)
        ],
        now=today.isoformat(timespec="seconds"),
    )


def _shadow_rows(db: str) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute(
            "SELECT ticker, event_key, horizon_days, created_at, resolve_after"
            " FROM evidence_predictions WHERE source = ?",
            (SOURCE_INSIDER_SHADOW,),
        ).fetchall()


def test_cluster_is_registered_once_with_a_trading_day_stamp(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_cluster(db)

    result = run_insider_shadow(db, now=NOW, env=ENV)

    assert result["status"] == "ok"
    assert result["clusters"] == 1 and result["registered"] == 1
    rows = _shadow_rows(db)
    assert len(rows) == 1
    ticker, event_key, horizon, created_at, resolve_after = rows[0]
    assert (ticker, event_key, horizon) == ("AAA", "2026-08-03-cluster3", 63)
    # 63 trading days ~ 93 calendar days: due means measurable.
    assert datetime.fromisoformat(resolve_after) - datetime.fromisoformat(created_at) == (
        timedelta(days=93)
    )


def test_second_run_registers_nothing_while_the_prediction_is_open(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_cluster(db)
    run_insider_shadow(db, now=NOW, env=ENV)

    result = run_insider_shadow(db, now="2026-08-11T18:45:00+00:00", env=ENV)

    assert result["registered"] == 0 and result["skipped_open"] == 1
    assert len(_shadow_rows(db)) == 1


def test_two_insiders_register_nothing(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_cluster(db, n=2)
    result = run_insider_shadow(db, now=NOW, env=ENV)
    assert result["clusters"] == 0 and result["registered"] == 0
    assert _shadow_rows(db) == []


def test_events_outside_the_window_do_not_form_a_cluster(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_cluster(db)
    result = run_insider_shadow(db, now="2026-11-01T18:45:00+00:00", env=ENV)
    assert result["clusters"] == 0 and result["insider_events"] == 0


def test_no_events_and_no_user_agent_reports_unconfigured(tmp_path):
    """A dead source must never look like a quiet one (evidence/base.py status contract)."""
    db = str(tmp_path / "es.db")
    result = run_insider_shadow(db, now=NOW, env={})
    assert result["status"] == "unconfigured"
    assert "EDGAR_USER_AGENT" in result["detail"]
    assert result["registered"] == 0


def test_no_events_with_a_user_agent_is_an_honest_quiet_day(tmp_path):
    db = str(tmp_path / "es.db")
    result = run_insider_shadow(db, now=NOW, env=ENV)
    assert result["status"] == "ok" and result["registered"] == 0


def test_dry_run_detects_but_writes_nothing(tmp_path):
    db = str(tmp_path / "es.db")
    _seed_cluster(db)
    result = run_insider_shadow(db, now=NOW, env=ENV, apply=False)
    assert result["clusters"] == 1 and result["registered"] == 0
    assert _shadow_rows(db) == []


def test_main_exits_zero_and_prints_a_summary(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "es.db")
    _seed_cluster_today(db)
    monkeypatch.setattr(sys, "argv", ["run_insider_shadow.py", "--db", db])

    assert main() == 0

    out = capsys.readouterr().out
    assert "Schatten-Lane" in out and "AAA" in out
    assert stats_by_source(db)[SOURCE_INSIDER_SHADOW]["n_open"] == 1
