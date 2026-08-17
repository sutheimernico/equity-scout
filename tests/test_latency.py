"""Latency decay: what a delayed entry misses, what it can still earn, and the verdict."""
import pandas as pd

from equity_scout.matrix.latency import (
    DELAY_MINUTES,
    HOLD_MINUTES,
    MIN_EVENTS,
    decay_verdict,
    event_moves,
    summarise,
)


def _bars(closes: list[float], start: str = "2024-01-02T14:30:00Z") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(closes), freq="1min")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [100] * len(closes)},
        index=index, dtype=float,
    )


def test_a_delayed_entry_misses_the_move_that_already_happened():
    # 100 -> 101 in the first minute, then flat: entering 1 minute late misses 100 bp
    bars = _bars([100.0, 101.0] + [101.0] * 60)
    stamps = pd.Series([pd.Timestamp("2024-01-02T14:30:00Z")])
    moves = event_moves(bars, stamps, delay_minutes=1, hold_minutes=5)
    assert round(float(moves["before_bp"][0])) == 100
    assert round(float(moves["after_bp"][0])) == 0


def test_a_prompt_entry_captures_the_move():
    bars = _bars([100.0, 101.0] + [101.0] * 60)
    stamps = pd.Series([pd.Timestamp("2024-01-02T14:30:00Z")])
    moves = event_moves(bars, stamps, delay_minutes=0, hold_minutes=5)
    assert round(float(moves["before_bp"][0])) == 0
    assert round(float(moves["after_bp"][0])) == 100


def test_an_event_whose_entry_falls_past_a_session_break_is_dropped():
    # bars end at 14:40, the wire item arrives at 14:39 -> a 30-minute hold has no exit bar
    bars = _bars([100.0] * 11)
    stamps = pd.Series([pd.Timestamp("2024-01-02T14:39:00Z")])
    moves = event_moves(bars, stamps, delay_minutes=0, hold_minutes=30)
    assert len(moves["after_bp"]) == 0


def test_a_gap_between_wire_and_entry_bar_beyond_the_guard_is_dropped():
    # the item arrives while the market is closed; the next bar is the following session
    bars = pd.concat([
        _bars([100.0] * 5, start="2024-01-02T20:55:00Z"),
        _bars([105.0] * 60, start="2024-01-03T14:30:00Z"),
    ])
    stamps = pd.Series([pd.Timestamp("2024-01-02T23:00:00Z")])  # after the close
    moves = event_moves(bars, stamps, delay_minutes=0, hold_minutes=5)
    assert len(moves["after_bp"]) == 0  # would otherwise book the overnight gap as a reaction


def test_summarise_reports_only_the_count_below_the_event_floor():
    bars = _bars([100.0, 101.0] + [101.0] * 60)
    stamps = pd.Series([pd.Timestamp("2024-01-02T14:30:00Z")])
    result = summarise(event_moves(bars, stamps, delay_minutes=0, hold_minutes=5), cost_bps=4.0)
    assert result["n"] == 1 and result["net_bp"] is None and result["t"] is None


def test_summarise_subtracts_costs_from_the_captured_move():
    # 150 identical events on a repeating +100 bp pattern -> above the floor, known answer
    bars = _bars([100.0, 101.0, 101.0] * 200)
    stamps = pd.Series([bars.index[i * 3] for i in range(150)])
    result = summarise(
        event_moves(bars, stamps, delay_minutes=0, hold_minutes=1), cost_bps=10.0
    )
    assert result["n"] >= MIN_EVENTS
    assert round(result["after_bp"]) == 100
    assert round(result["net_bp"]) == 90


def test_verdict_says_latency_is_no_constraint_when_the_effect_survives_five_minutes():
    rows = [{"delay_minutes": 5, "net_bp": 8.0, "t": 3.0},
            {"delay_minutes": 15, "net_bp": 6.0, "t": 2.5}]
    verdict = decay_verdict(rows)
    assert "nicht der Engpass" in verdict


def test_verdict_calls_an_unwinnable_race_by_its_name():
    rows = [{"delay_minutes": 0, "net_bp": 20.0, "t": 4.0},
            {"delay_minutes": 5, "net_bp": -2.0, "t": -0.5}]
    assert "Latenzrennen" in decay_verdict(rows)


def test_verdict_says_no_effect_when_nothing_is_significant():
    rows = [{"delay_minutes": 0, "net_bp": 1.0, "t": 0.4}]
    assert "keinen Effekt gibt" in decay_verdict(rows)


def test_verdict_refuses_to_judge_an_empty_measurement():
    assert "nicht entscheidbar" in decay_verdict([{"delay_minutes": 0, "net_bp": None, "t": None}])


def test_the_axes_are_the_documented_ones():
    assert DELAY_MINUTES == (0, 1, 2, 5, 15, 30)
    assert HOLD_MINUTES == (5, 15, 30, 60)
