"""Persisted lane parameters: constants as fallback, history written with every change."""
from __future__ import annotations

import pytest

from equity_scout.exits import ExitRules
from equity_scout.lane_params import (
    changed_this_month,
    history,
    load_params,
    set_params,
)

DEFAULT = ExitRules(profit_target=0.05, stop_loss=0.03, max_holding_days=7)


@pytest.fixture()
def db(tmp_path):
    return str(tmp_path / "shortterm.db")


def test_an_untouched_lane_runs_on_the_shipped_constants(db) -> None:
    """Empty table means 'as shipped', never 'no rules' — the lane has to be able to run."""
    assert load_params(db, "swing", default=DEFAULT) == DEFAULT


def test_a_written_parameter_set_is_read_back(db) -> None:
    tuned = ExitRules(profit_target=0.05, stop_loss=0.05, max_holding_days=14)
    set_params(db, "swing", tuned, reason="Suche", evidence={"t": 3.1}, now="2026-09-01T02:00:00Z")
    assert load_params(db, "swing", default=DEFAULT) == tuned


def test_lanes_do_not_share_parameters(db) -> None:
    set_params(db, "swing", ExitRules(0.08, 0.05, 14), reason="x", evidence={},
               now="2026-09-01T02:00:00Z")
    assert load_params(db, "session", default=DEFAULT) == DEFAULT


def test_every_change_writes_its_own_history_row(db) -> None:
    set_params(db, "swing", ExitRules(0.05, 0.05, 14), reason="erste Anpassung",
               evidence={"t_stat": 3.4, "n": 650}, now="2026-09-01T02:00:00Z")
    set_params(db, "swing", ExitRules(0.08, 0.05, 14), reason="zweite Anpassung",
               evidence={"t_stat": 3.9, "n": 700}, now="2026-10-01T02:00:00Z")
    rows = history(db, "swing")
    assert [r.reason for r in rows] == ["zweite Anpassung", "erste Anpassung"]  # newest first
    assert rows[0].evidence["n"] == 700
    assert rows[1].profit_target == pytest.approx(0.05)


def test_the_evidence_survives_the_round_trip(db) -> None:
    """A change without its evidence is a number nobody can interpret six weeks later."""
    set_params(db, "swing", ExitRules(0.05, 0.05, 14), reason="Suche",
               evidence={"challenger_t": 3.4, "incumbent_t": 2.8, "trials": 36},
               now="2026-09-01T02:00:00Z")
    assert history(db, "swing")[0].evidence["trials"] == 36


def test_the_monthly_brake_sees_a_change_in_the_same_month(db) -> None:
    set_params(db, "swing", ExitRules(0.05, 0.05, 14), reason="x", evidence={},
               now="2026-09-15T02:00:00Z")
    assert changed_this_month(db, "swing", month="2026-09")
    assert not changed_this_month(db, "swing", month="2026-10")
    assert not changed_this_month(db, "session", month="2026-09")
