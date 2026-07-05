"""Two-lane paper execution engine.

Lane "nico" trades only pitches Nico approved; lane "autopilot" trades the score
autonomously. FAIRNESS INVARIANT: both lanes are advanced in the same run with the
same prices dict, the same sizing/fee/slippage parameters and the same ExitRules —
the comparison is only honest if nothing here diverges per lane.

Reuses portfolio.py's Position/Portfolio mechanics (imported, not copied). Exits are
deliberately simple v1 rules (spec §7): profit target, stop loss, max holding period.
Every action emits a structured TradeRecord — the persisted audit trail that also
serves as the "pitch executed" marker via pitch_id.

PAPER ONLY. No real orders, ever.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from equity_scout.portfolio import Portfolio, Position

LANE_NICO = "nico"
LANE_AUTOPILOT = "autopilot"

DEFAULT_POSITION_FRACTION = 0.05
DEFAULT_FEE_RATE = 0.001
DEFAULT_SLIPPAGE_BPS = 5.0


@dataclass(frozen=True)
class ExitRules:
    """v1 exit rules (spec §7): deliberately simple and identical for both lanes."""

    profit_target: float = 0.20  # sell when price > cost_basis * (1 + target)
    stop_loss: float = 0.15  # sell when price < cost_basis * (1 - stop)
    max_holding_days: int = 180  # sell when held longer than this


@dataclass(frozen=True)
class BuyOrder:
    ticker: str
    name: str
    score: float
    reason: str  # German, shown in the trade log
    pitch_id: int | None  # set for lane "nico" (links back to the decided pitch)


@dataclass(frozen=True)
class TradeRecord:
    created_at: str
    lane: str
    ticker: str
    side: str  # "buy" | "sell"
    shares: float
    fill_price: float
    cost: float  # cash delta magnitude incl. fees (buy: spent; sell: proceeds)
    reason: str  # German
    pitch_id: int | None = None


def _held_days(opened_at: str, now: str) -> int:
    return (datetime.fromisoformat(now) - datetime.fromisoformat(opened_at)).days


def _exit_reason(position: Position, price: float, now: str, rules: ExitRules) -> str | None:
    if price > position.cost_basis * (1.0 + rules.profit_target):
        return f"Kursziel erreicht (+{rules.profit_target * 100:.0f} %)"
    if price < position.cost_basis * (1.0 - rules.stop_loss):
        return f"Stop-Loss ausgelöst (−{rules.stop_loss * 100:.0f} %)"
    if _held_days(position.opened_at, now) > rules.max_holding_days:
        return f"Maximale Haltedauer überschritten ({rules.max_holding_days} Tage)"
    return None


def apply_exits(
    portfolio: Portfolio,
    prices: dict[str, float],
    *,
    now: str,
    lane: str,
    rules: ExitRules,
    fee_rate: float = DEFAULT_FEE_RATE,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> tuple[Portfolio, list[TradeRecord]]:
    """Sell every position that violates a rule; refresh last_price on the rest.

    A position without a current price is held untouched (cannot value a sale) —
    same stance as portfolio.advance.
    """
    slip = slippage_bps / 10_000.0
    cash = portfolio.cash
    positions = dict(portfolio.positions)
    trades: list[TradeRecord] = []
    for ticker in list(positions):
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        reason = _exit_reason(positions[ticker], price, now, rules)
        if reason is None:
            positions[ticker] = replace(positions[ticker], last_price=price)
            continue
        fill = price * (1 - slip)
        proceeds = positions[ticker].shares * fill * (1 - fee_rate)
        cash += proceeds
        trades.append(
            TradeRecord(
                created_at=now, lane=lane, ticker=ticker, side="sell",
                shares=positions[ticker].shares, fill_price=round(fill, 4),
                cost=round(proceeds, 2), reason=reason,
            )
        )
        del positions[ticker]
    return replace(portfolio, cash=cash, positions=positions), trades
