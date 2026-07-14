"""Lane engine tests — pure functions, synthetic portfolios, no network."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from equity_scout.lanes import (
    DEFAULT_FEE_RATE,
    DEFAULT_SLIPPAGE_BPS,
    LANE_AUTOPILOT,
    LANE_NICO,
    BuyOrder,
    ExitRules,
    TradeRecord,
    apply_exits,
    execute_buys,
    lane_b_orders,
)
from equity_scout.models import Instrument
from equity_scout.portfolio import Portfolio, Position, new_portfolio

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


def _order(ticker: str, pitch_id: int | None = None, score: float = 0.6) -> BuyOrder:
    return BuyOrder(ticker=ticker, name=f"{ticker} Corp", score=score,
                    reason="Testgrund", pitch_id=pitch_id)


def test_execute_buys_fills_with_slippage_and_links_pitch():
    portfolio = new_portfolio(initial_capital=10_000.0)
    updated, trades = execute_buys(
        portfolio, [_order("NEW", pitch_id=7)], {"NEW": 100.0}, now=NOW, lane=LANE_NICO
    )
    position = updated.positions["NEW"]
    assert position.cost_basis > 100.0  # buys fill above the quote
    assert abs(position.shares * position.cost_basis - 500.0) < 0.01  # 5% of capital
    assert updated.cash < 10_000.0 - 500.0  # fees on top
    trade = trades[0]
    assert (trade.side, trade.pitch_id) == ("buy", 7)


def test_execute_buys_skips_held_unpriced_and_underfunded():
    portfolio = new_portfolio(initial_capital=10_000.0)
    portfolio, _ = execute_buys(
        portfolio, [_order("HELD")], {"HELD": 100.0}, now=NOW, lane=LANE_NICO
    )
    # cash=0 is underfunded for any positive target_value regardless of how it's sized
    # (equity-based sizing still yields > 0 target_value from the HELD position's value).
    poor = replace(portfolio, cash=0.0)
    updated, trades = execute_buys(
        poor,
        [_order("HELD"), _order("DARK"), _order("POOR")],
        {"HELD": 100.0, "POOR": 50.0},
        now=NOW,
        lane=LANE_NICO,
    )
    assert set(updated.positions) == {"HELD"}
    assert trades == []


def test_new_buy_sized_larger_after_big_gain():
    # Baseline: fresh account buys BASE at 100, sized off 10_000 starting equity.
    portfolio = new_portfolio(initial_capital=10_000.0)
    portfolio, _ = execute_buys(
        portfolio, [_order("BASE")], {"BASE": 100.0}, now=NOW, lane=LANE_NICO,
        fee_rate=0.001, slippage_bps=0.0,
    )
    baseline_shares = portfolio.positions["BASE"].shares  # 500 stake / 100 = 5.0 shares

    # BASE gains 10x (100 -> 1000), ballooning current equity well above initial_capital.
    # A fresh order MORE should now be sized off that larger current equity.
    updated, _ = execute_buys(
        portfolio, [_order("MORE")], {"BASE": 1000.0, "MORE": 100.0}, now=NOW, lane=LANE_NICO,
        fee_rate=0.001, slippage_bps=0.0,
    )
    assert "MORE" in updated.positions
    assert updated.positions["MORE"].shares > baseline_shares


def test_new_buy_sized_smaller_after_big_loss():
    # Baseline: fresh account buys BASE at 100, sized off 10_000 starting equity.
    portfolio = new_portfolio(initial_capital=10_000.0)
    portfolio, _ = execute_buys(
        portfolio, [_order("BASE")], {"BASE": 100.0}, now=NOW, lane=LANE_NICO,
        fee_rate=0.001, slippage_bps=0.0,
    )
    baseline_shares = portfolio.positions["BASE"].shares  # 500 stake / 100 = 5.0 shares

    # BASE craters 80% (100 -> 20), shrinking current equity below initial_capital.
    # A fresh order LESS should now be sized off that smaller current equity.
    updated, _ = execute_buys(
        portfolio, [_order("LESS")], {"BASE": 20.0, "LESS": 100.0}, now=NOW, lane=LANE_NICO,
        fee_rate=0.001, slippage_bps=0.0,
    )
    assert "LESS" in updated.positions
    assert updated.positions["LESS"].shares < baseline_shares


def test_lane_b_orders_from_watchlist():
    watchlist = {
        "entries": [
            {"ticker": "YES", "name": "Yes Corp", "in_zone": True, "composite": 0.6,
             "zone_note": "In der Zone."},
            {"ticker": "HELD", "name": "Held Corp", "in_zone": True, "composite": 0.9,
             "zone_note": "In der Zone."},
            {"ticker": "LOW", "name": "Low Corp", "in_zone": True, "composite": 0.2,
             "zone_note": "In der Zone."},
            {"ticker": "OUT", "name": "Out Corp", "in_zone": False, "composite": 0.9,
             "zone_note": "Drüber."},
        ]
    }
    orders = lane_b_orders(watchlist, held_tickers={"HELD"}, threshold=0.45)
    assert [o.ticker for o in orders] == ["YES"]
    assert orders[0].pitch_id is None
    assert orders[0].score == 0.6


def test_sell_proceeds_apply_fee_in_the_right_direction():
    """Cash delta and trade.cost == raw_shares * fill * (1 - fee_rate); a flipped fee sign
    (1 + fee_rate) must fail this. Recorded shares round to 4dp, proceeds use raw shares."""
    pos = Position(_instrument("WIN"), shares=5.123456, cost_basis=100.0,
                   opened_at="2026-06-01T14:00:00+00:00")
    portfolio = Portfolio(initial_capital=10_000.0, cash=5_000.0, positions={"WIN": pos})
    updated, trades = apply_exits(
        portfolio, {"WIN": 130.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    fill = 130.0 * (1 - DEFAULT_SLIPPAGE_BPS / 10_000.0)
    expected_proceeds = 5.123456 * fill * (1 - DEFAULT_FEE_RATE)
    assert updated.cash == portfolio.cash + expected_proceeds
    assert trades[0].cost == round(expected_proceeds, 2)
    assert trades[0].shares == round(5.123456, 4)  # recorded shares rounded, proceeds raw


def test_stop_loss_boundary_is_exclusive():
    """Price at exactly cost_basis * 0.85 is NOT a stop-loss exit (strict `<`)."""
    portfolio = _portfolio(EDGE=_position("EDGE", cost=100.0))
    updated, trades = apply_exits(
        portfolio, {"EDGE": 85.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    assert "EDGE" in updated.positions
    assert trades == []


def test_max_holding_boundary_is_exclusive():
    """Holding for exactly max_holding_days (180) is NOT a max-holding exit (strict `>`)."""
    opened_at = (datetime.fromisoformat(NOW) - timedelta(days=180)).isoformat()
    edge = Position(_instrument("EDGE"), shares=10.0, cost_basis=100.0, opened_at=opened_at)
    portfolio = Portfolio(initial_capital=10_000.0, cash=5_000.0, positions={"EDGE": edge})
    updated, trades = apply_exits(
        portfolio, {"EDGE": 101.0}, now=NOW, lane=LANE_NICO, rules=RULES
    )
    assert "EDGE" in updated.positions
    assert trades == []
