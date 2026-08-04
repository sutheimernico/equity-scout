"""Nightly Auto-Depot push: materiality threshold (Telegram diet, 2026-08-04).

A dozen sub-1 % rebalances used to produce a dozen lines; only material moves and risk
events are worth a push at all.
"""
from __future__ import annotations

from dataclasses import dataclass

from scripts.run_autotrader import build_event_message


@dataclass
class FakeTrade:
    ticker: str
    delta_weight: float
    notional: float


@dataclass
class FakeEvent:
    detail: str


@dataclass
class FakeValuation:
    created_at: str
    trades: list
    risk_events: list


def test_no_message_when_only_immaterial_trades_happened():
    valuation = FakeValuation(
        "2026-08-03",
        [FakeTrade("XLK", -0.0006, 60.0), FakeTrade("BIL", 0.0006, 60.0)],
        [],
    )
    assert build_event_message(valuation) is None


def test_immaterial_trades_still_push_when_a_risk_event_fired():
    valuation = FakeValuation(
        "2026-08-03",
        [FakeTrade("XLK", -0.0006, 60.0)],
        [FakeEvent("Einzeltitel-Limit 10% griff bei: SPY")],
    )
    message = build_event_message(valuation)
    assert message is not None
    assert "⚠ Einzeltitel-Limit 10% griff bei: SPY" in message
    assert "1 kleine Rebalance" in message


def test_material_trades_are_named_with_direction_and_size():
    valuation = FakeValuation(
        "2026-08-03",
        [FakeTrade("MU", -0.041, 4100.0), FakeTrade("XLK", -0.0006, 60.0)],
        [],
    )
    message = build_event_message(valuation)
    assert "🤖 Auto-Depot 2026-08-03" in message
    assert "• VERKAUF MU 4,1 % (~4.100 $)" in message
    assert "1 kleine Rebalance" in message


def test_quiet_advance_stays_silent():
    assert build_event_message(FakeValuation("2026-08-03", [], [])) is None
    assert build_event_message(None) is None


def test_material_trades_beyond_the_cap_are_not_called_small():
    """Review catch (2026-08-04): counting over-cap MATERIAL trades as "kleine
    Rebalance" would report a 3 % move as bookkeeping. The two remainders stay apart."""
    trades = [FakeTrade(f"T{i}", -0.03 - i / 1000, 3000.0) for i in range(7)]
    trades.append(FakeTrade("XLK", -0.0006, 60.0))
    message = build_event_message(FakeValuation("2026-08-03", trades, []))
    assert message is not None
    assert "+2 weitere über der Schwelle" in message  # 7 material, 5 named
    assert "1 kleine Rebalance" in message           # the sub-threshold one
