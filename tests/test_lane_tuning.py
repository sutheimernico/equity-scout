"""Lane parameter search: same exit logic as the live lane, honest handling of edge cases."""
from __future__ import annotations

import pandas as pd
import pytest

from equity_scout.exits import ExitRules
from equity_scout.lane_tuning import (
    evaluate,
    grid,
    search,
    simulate_event,
)


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range("2026-01-01", periods=len(values)))


def test_profit_target_exit_stops_the_walk() -> None:
    closes = _series([100.0, 103.0, 106.0, 200.0])
    ret, reason = simulate_event(closes, 0, ExitRules(0.05, 0.03, 7))
    assert "Kursziel" in reason
    assert ret == pytest.approx(0.06)  # exits at +6 %, never sees the 200


def test_stop_loss_fires_before_the_target() -> None:
    closes = _series([100.0, 96.0, 130.0])
    ret, reason = simulate_event(closes, 0, ExitRules(0.05, 0.03, 7))
    assert "Stop-Loss" in reason
    assert ret == pytest.approx(-0.04)


def test_holding_period_closes_a_position_that_never_hit_a_barrier() -> None:
    closes = _series([100.0] * 10)
    ret, reason = simulate_event(closes, 0, ExitRules(0.05, 0.03, 3))
    assert "Haltedauer" in reason
    assert ret == pytest.approx(0.0)


def test_a_series_that_ends_first_says_so_instead_of_disappearing() -> None:
    """Dropping these would remove exactly the trades that ran longest."""
    closes = _series([100.0, 101.0, 102.0])
    ret, reason = simulate_event(closes, 0, ExitRules(0.50, 0.50, 999))
    assert reason == "Reihe zu Ende"
    assert ret == pytest.approx(0.02)


def test_entry_is_the_close_after_the_event_not_the_event_bar() -> None:
    # Event on day 0; the lane may only act on the next close, which is 90 here.
    closes = _series([100.0, 90.0, 94.5])
    trial = evaluate({"X": closes}, [("X", closes.index[0])],
                     profit_target=0.05, stop_loss=0.99, max_days=7)
    assert trial.n_trades == 1
    assert trial.mean_pnl_pct == pytest.approx(0.05)  # 90 -> 94.5, not 100 -> ...


def test_events_without_price_history_are_skipped_not_counted_as_zero() -> None:
    trial = evaluate({"X": _series([100.0, 101.0])}, [("MISSING", pd.Timestamp("2026-01-01"))],
                     profit_target=0.05, stop_loss=0.03, max_days=7)
    assert trial.n_trades == 0
    assert trial.mean_pnl_pct == 0.0


def test_exit_mix_records_where_the_trades_ended() -> None:
    winner = _series([100.0, 100.0, 110.0])
    loser = _series([100.0, 100.0, 90.0])
    trial = evaluate({"W": winner, "L": loser},
                     [("W", winner.index[0]), ("L", loser.index[0])],
                     profit_target=0.05, stop_loss=0.03, max_days=7)
    assert trial.n_trades == 2
    assert sum(trial.exit_mix.values()) == 2
    assert trial.win_rate == pytest.approx(0.5)


def test_a_trial_carries_its_spread_so_two_candidates_can_be_compared() -> None:
    """A mean without a spread cannot be compared to another mean. The entry registry held a
    champion for five weeks precisely because two point estimates looked comparable."""
    up = _series([100.0, 100.0, 110.0])
    down = _series([100.0, 100.0, 90.0])
    trial = evaluate({"A": up, "B": down}, [("A", up.index[0]), ("B", down.index[0])],
                     profit_target=0.05, stop_loss=0.03, max_days=7)
    assert trial.stdev_pnl_pct > 0
    assert trial.t_stat is not None


def test_a_single_trade_reports_no_t_statistic_rather_than_a_fake_one() -> None:
    closes = _series([100.0, 100.0, 110.0])
    trial = evaluate({"A": closes}, [("A", closes.index[0])],
                     profit_target=0.05, stop_loss=0.03, max_days=7)
    assert trial.n_trades == 1
    assert trial.t_stat is None


def test_grid_is_stable_because_the_cursor_indexes_into_it() -> None:
    assert grid() == grid()
    assert len(grid()) == 4 * 3 * 3


def test_search_slice_wraps_around_the_space() -> None:
    closes = {"X": _series([100.0, 101.0, 102.0, 103.0])}
    events = [("X", closes["X"].index[0])]
    trials = search(closes, events, limit=len(grid()) + 2, start=0)
    assert len(trials) == len(grid()) + 2  # wraps rather than running off the end
