"""Paper-trading portfolio: buy-and-hold forward tracking of equity-scout picks.

PAPER ONLY — no real orders, ever. The point is to forward-test whether high-composite picks turn
out to be good investments over time, measured against a buy-and-hold benchmark. Pure functions:
buying and valuation are deterministic given prices; the caller supplies live prices and timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from equity_scout.models import Instrument, Pick


@dataclass(frozen=True)
class Position:
    instrument: Instrument
    shares: float
    cost_basis: float  # price per share at purchase
    opened_at: str


@dataclass(frozen=True)
class Portfolio:
    initial_capital: float
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    benchmark_ticker: str = "SPY"
    benchmark_shares: float = 0.0


@dataclass(frozen=True)
class Valuation:
    total_value: float
    invested: float
    total_return: float
    cash: float
    positions_value: float
    benchmark_value: float
    benchmark_return: float
    open_positions: int


def new_portfolio(initial_capital: float = 100_000.0, benchmark_ticker: str = "SPY") -> Portfolio:
    return Portfolio(
        initial_capital=initial_capital, cash=initial_capital, benchmark_ticker=benchmark_ticker
    )


def advance(
    portfolio: Portfolio,
    candidate_picks: list[Pick],
    prices: dict[str, float],
    *,
    now: str,
    threshold: float = 0.70,
    position_fraction: float = 0.05,
    fee_rate: float = 0.001,
    benchmark_price: float | None = None,
) -> tuple[Portfolio, list[str]]:
    """Buy fresh picks with composite >= threshold at an equal target value (buy-and-hold).

    Skips picks already held, below threshold, without a price, or unaffordable. Initializes the
    benchmark position on the first advance. Returns (updated portfolio, human-readable trades).
    """
    cash = portfolio.cash
    positions = dict(portfolio.positions)
    benchmark_shares = portfolio.benchmark_shares
    trades: list[str] = []

    if benchmark_shares == 0.0 and benchmark_price:
        benchmark_shares = portfolio.initial_capital / benchmark_price

    target_value = portfolio.initial_capital * position_fraction
    for pick in candidate_picks:
        ticker = pick.instrument.ticker
        price = prices.get(ticker)
        if pick.composite < threshold or ticker in positions or not price:
            continue
        total_cost = target_value * (1 + fee_rate)
        if cash < total_cost:
            continue
        shares = target_value / price
        cash -= total_cost
        positions[ticker] = Position(pick.instrument, shares, price, now)
        trades.append(f"BUY {ticker} {shares:.2f}@{price:.2f} (composite {pick.composite:.2f})")

    updated = replace(portfolio, cash=cash, positions=positions, benchmark_shares=benchmark_shares)
    return updated, trades


def mark_to_market(
    portfolio: Portfolio, prices: dict[str, float], benchmark_price: float | None = None
) -> Valuation:
    """Value the portfolio at current prices. Falls back to cost basis for a missing price."""
    positions_value = sum(
        pos.shares * prices.get(ticker, pos.cost_basis)
        for ticker, pos in portfolio.positions.items()
    )
    total_value = portfolio.cash + positions_value
    invested = portfolio.initial_capital
    benchmark_value = (
        portfolio.benchmark_shares * benchmark_price
        if benchmark_price and portfolio.benchmark_shares
        else invested
    )
    return Valuation(
        total_value=total_value,
        invested=invested,
        total_return=(total_value - invested) / invested if invested else 0.0,
        cash=portfolio.cash,
        positions_value=positions_value,
        benchmark_value=benchmark_value,
        benchmark_return=(benchmark_value - invested) / invested if invested else 0.0,
        open_positions=len(portfolio.positions),
    )
