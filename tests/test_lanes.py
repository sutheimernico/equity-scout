"""Lane engine tests — pure functions, synthetic portfolios, no network."""
from __future__ import annotations

from equity_scout.lanes import (
    LANE_AUTOPILOT,
    LANE_NICO,
    ExitRules,
    TradeRecord,
    apply_exits,
)
from equity_scout.models import Instrument
from equity_scout.portfolio import Portfolio, Position

NOW = "2026-07-05T14:00:00+00:00"
RULES = ExitRules()  # defaults: profit_target=0.20, stop_loss=0.15, max_holding_days=180


def _instrument(ticker: str) -> Instrument:
    return Instrument(ticker, f"{ticker} Corp", "", "", "", "")


def _portfolio(**positions: Position) -> Portfolio:
    return Portfolio(initial_capital=10_000.0, cash=5_000.0, positions=dict(positions))


def _position(ticker: str, cost: float, opened_at: str = "2026-06-01T14:00:00+00:00") -> Position:
    return Position(_instrument(ticker), shares=10.0, cost_basis=cost, opened_at=opened_at)


def test_exit_on_profit_target():
    portfolio = _portfolio(WIN=_position("WIN", cost=100.0))
    updated, trades = apply_exits(
        portfolio, {"WIN": 121.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    assert "WIN" not in updated.positions
    assert len(trades) == 1
    trade = trades[0]
    assert isinstance(trade, TradeRecord)
    assert (trade.lane, trade.ticker, trade.side) == (LANE_NICO, "WIN", "sell")
    assert trade.fill_price < 121.0  # sells into slippage
    assert "Kursziel" in trade.reason
    assert updated.cash > portfolio.cash


def test_exit_on_stop_loss():
    portfolio = _portfolio(LOSE=_position("LOSE", cost=100.0))
    updated, trades = apply_exits(
        portfolio, {"LOSE": 84.0}, now=NOW, lane=LANE_AUTOPILOT, rules=RULES
    )
    assert "LOSE" not in updated.positions
    assert "Stop-Loss" in trades[0].reason


def test_exit_on_max_holding_days():
    old = _position("OLD", cost=100.0, opened_at="2025-12-01T14:00:00+00:00")
    updated, trades = apply_exits(
        _portfolio(OLD=old), {"OLD": 101.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    assert "OLD" not in updated.positions
    assert "Haltedauer" in trades[0].reason


def test_holds_inside_all_rules_and_without_price():
    keep = _position("KEEP", cost=100.0)
    noprice = _position("DARK", cost=100.0)
    portfolio = _portfolio(KEEP=keep, DARK=noprice)
    updated, trades = apply_exits(
        portfolio, {"KEEP": 105.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    assert set(updated.positions) == {"KEEP", "DARK"}
    assert trades == []
    assert updated.positions["KEEP"].last_price == 105.0  # refreshed for the dashboard


def test_exit_boundary_is_exclusive():
    at_target = _portfolio(EDGE=_position("EDGE", cost=100.0))
    updated, trades = apply_exits(
        at_target, {"EDGE": 120.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    assert "EDGE" in updated.positions  # exactly +20% is NOT yet an exit (> not >=)
    assert trades == []
