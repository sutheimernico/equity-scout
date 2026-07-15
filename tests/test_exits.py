"""Shared exit-rule threshold tests (plan v7, strand A2): profit target, stop loss, max holding —
pure function, no I/O. Position-based application for the arena lanes lives in test_lanes.py (via
lanes.apply_exits, which now delegates its threshold check here); this file only covers the shared
decision both lanes.py and forward_paper.py call into."""
from __future__ import annotations

from equity_scout.exits import ExitRules, exit_reason

RULES = ExitRules()  # defaults: profit_target=0.20, stop_loss=0.15, max_holding_days=180


def test_profit_target_triggers_above_threshold():
    reason = exit_reason(0.21, held_days=10, rules=RULES)
    assert reason is not None
    assert "Kursziel" in reason


def test_profit_target_boundary_is_exclusive():
    assert exit_reason(0.20, held_days=10, rules=RULES) is None


def test_stop_loss_triggers_below_threshold():
    reason = exit_reason(-0.16, held_days=10, rules=RULES)
    assert reason is not None
    assert "Stop-Loss" in reason


def test_stop_loss_boundary_is_exclusive():
    assert exit_reason(-0.15, held_days=10, rules=RULES) is None


def test_max_holding_days_triggers_above_threshold():
    reason = exit_reason(0.0, held_days=181, rules=RULES)
    assert reason is not None
    assert "Haltedauer" in reason


def test_max_holding_days_boundary_is_exclusive():
    assert exit_reason(0.0, held_days=180, rules=RULES) is None


def test_holds_inside_all_thresholds():
    assert exit_reason(0.05, held_days=30, rules=RULES) is None


def test_profit_target_checked_before_max_holding():
    """Both conditions true at once: profit target wins (checked first) — same precedence as the
    pre-extraction lanes._exit_reason."""
    reason = exit_reason(0.25, held_days=200, rules=RULES)
    assert reason is not None
    assert "Kursziel" in reason


def test_custom_rules_are_respected():
    tight = ExitRules(profit_target=0.05, stop_loss=0.05, max_holding_days=10)
    assert exit_reason(0.06, held_days=1, rules=tight) is not None
    assert exit_reason(0.02, held_days=1, rules=tight) is None
