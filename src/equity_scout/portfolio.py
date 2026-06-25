"""Paper-trading portfolio: rule-based forward tracking of equity-scout picks.

PAPER ONLY — no real orders, ever. The point is to forward-test whether high-composite picks turn
out to be good investments over time, measured against a buy-and-hold benchmark. Pure functions:
trading and valuation are deterministic given prices; the caller supplies live prices and timestamps.

Trading is rule-based with hysteresis, not a forecast: buy a fresh pick when its composite clears the
entry threshold; sell a held position once its composite falls below the (lower) exit threshold or it
drops out of the screen entirely. Both legs pay a flat commission and slippage on the fill — a
position that round-trips is charged twice, so churn costs money (the honest part).
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
    last_price: float | None = None  # most recent price seen, for per-position P&L


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
    exit_threshold: float = 0.55,
    position_fraction: float = 0.05,
    fee_rate: float = 0.001,
    slippage_bps: float = 5.0,
    benchmark_price: float | None = None,
) -> tuple[Portfolio, list[str]]:
    """Rebalance the paper portfolio against the latest picks. Sell weak holdings, then buy fresh picks.

    Hysteresis avoids whipsaw: enter at composite >= ``threshold``, exit only once a holding's composite
    falls below the lower ``exit_threshold`` (a holding that dropped out of the screen counts as 0).
    Both legs pay ``fee_rate`` commission plus ``slippage_bps`` against the fill (buys fill above the
    quote, sells below). Initializes the benchmark on the first advance. Returns (portfolio, trades).
    """
    cash = portfolio.cash
    positions = dict(portfolio.positions)
    benchmark_shares = portfolio.benchmark_shares
    trades: list[str] = []
    slip = slippage_bps / 10_000.0

    if benchmark_shares == 0.0 and benchmark_price:
        benchmark_shares = portfolio.initial_capital / benchmark_price

    # A held ticker absent from the current screen counts as composite 0 → an exit candidate.
    composite_by_ticker = {p.instrument.ticker: p.composite for p in candidate_picks}

    # Sell leg first, so freed cash can fund new buys this same advance.
    for ticker in list(positions):
        price = prices.get(ticker)
        if price is None:
            continue  # cannot value a sale without a price; hold until we can
        if composite_by_ticker.get(ticker, 0.0) >= exit_threshold:
            continue  # still strong enough to hold
        fill = price * (1 - slip)  # sell into slippage
        proceeds = positions[ticker].shares * fill * (1 - fee_rate)
        cash += proceeds
        composite = composite_by_ticker.get(ticker, 0.0)
        trades.append(f"SELL {ticker} {positions[ticker].shares:.2f}@{fill:.2f} (composite {composite:.2f})")
        del positions[ticker]

    target_value = portfolio.initial_capital * position_fraction
    for pick in candidate_picks:
        ticker = pick.instrument.ticker
        price = prices.get(ticker)
        if pick.composite < threshold or ticker in positions or not price:
            continue
        fill = price * (1 + slip)  # buy into slippage
        total_cost = target_value * (1 + fee_rate)
        if cash < total_cost:
            continue
        shares = target_value / fill
        cash -= total_cost
        positions[ticker] = Position(pick.instrument, shares, fill, now)
        trades.append(f"BUY {ticker} {shares:.2f}@{fill:.2f} (composite {pick.composite:.2f})")

    # Refresh last_price for every held position where we have a current price, so the dashboard
    # can show per-position gain/loss without re-fetching.
    positions = {
        ticker: (replace(pos, last_price=prices[ticker]) if ticker in prices else pos)
        for ticker, pos in positions.items()
    }

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
