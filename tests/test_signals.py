"""Tests for entry sub-signals. Histories are synthetic and deterministic."""
from __future__ import annotations

from equity_scout.entry import compute_entry_plan
from equity_scout.signals import SignalReading, dip_quality, value_gap


def downtrend_history(
    n: int = 260, start: float = 100.0, end: float = 72.0
) -> tuple[list[float], list[float], list[float]]:
    """Linear decline over n days; highs/lows hug the closes."""
    step = (end - start) / (n - 1)
    closes = [start + step * i for i in range(n)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    return closes, highs, lows


def flat_history(
    n: int = 260, level: float = 100.0
) -> tuple[list[float], list[float], list[float]]:
    closes = [level + (0.4 if i % 2 else -0.4) for i in range(n)]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    return closes, highs, lows


def test_dip_quality_rewards_deep_dip_in_quality_stock():
    plan = compute_entry_plan("AAA", *downtrend_history())
    strong = dip_quality({"quality": 0.9}, plan)
    weak = dip_quality({"quality": 0.1}, plan)
    assert isinstance(strong, SignalReading)
    assert strong.name == "dip_quality"
    assert 0.0 <= weak.score < strong.score <= 1.0
    assert "52-Wochen-Hoch" in strong.reason


def test_dip_quality_is_low_without_a_dip():
    plan = compute_entry_plan("BBB", *flat_history())
    reading = dip_quality({"quality": 0.9}, plan)
    assert reading.score < 0.15


def test_dip_quality_missing_quality_percentile_scores_zero():
    plan = compute_entry_plan("CCC", *downtrend_history())
    assert dip_quality({}, plan).score == 0.0


def test_value_gap_rewards_discount_below_anchor_in_cheap_stock():
    plan = compute_entry_plan("AAA", *downtrend_history())  # price well below sma200
    cheap = value_gap({"value": 0.9}, plan)
    rich = value_gap({"value": 0.1}, plan)
    assert cheap.name == "value_gap"
    assert 0.0 <= rich.score < cheap.score <= 1.0
    assert "200-Tage-Schnitt" in cheap.reason


def test_value_gap_zero_above_anchor():
    closes, highs, lows = downtrend_history()
    closes.extend([c * 1.6 for c in closes[-40:]])  # rally far above the long-term mean
    highs.extend([c * 1.01 for c in closes[-40:]])
    lows.extend([c * 0.99 for c in closes[-40:]])
    plan = compute_entry_plan("DDD", closes, highs, lows)
    reading = value_gap({"value": 0.9}, plan)
    assert reading.score == 0.0
    assert "keine Bewertungslücke" in reading.reason


def test_value_gap_zero_without_sma200_data():
    plan = compute_entry_plan("EEE", *downtrend_history(n=50))
    # sma() falls back to fewer closes, so sma200 exists; force the None branch directly:
    from dataclasses import replace

    reading = value_gap({"value": 0.9}, replace(plan, sma200=None))
    assert reading.score == 0.0
