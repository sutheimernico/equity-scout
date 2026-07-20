"""Shared position book for the short-term arena lanes (vision v11).

One lightweight, share-based book per lane (`swing` / `session` / `crypto`): cash plus
long-only positions, every fill charged fee+slippage explicitly, and REALIZED per-trade
P&L as a first-class result — the arena's whole question ("was rentiert sich?") is
answered by realized outcomes and costs, not by marked equity alone.

Deliberately NOT `portfolio.py`: that model is coupled to Instruments, dividends and the
screener flow. This book is the minimal honest ledger the three lanes share. Long-only by
design (v1): short selling without a borrow/margin model would be fantasy realism.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

DEFAULT_FEE_BPS = 0.0  # zero-commission brokers; regulatory fees ride in slippage
DEFAULT_SLIPPAGE_BPS = 5.0


@dataclass(frozen=True)
class LanePosition:
    qty: float
    entry_price: float  # effective (slippage-adjusted) fill price
    opened_at: str  # ISO timestamp of the entry fill


@dataclass(frozen=True)
class LaneBook:
    lane: str
    initial_capital: float
    cash: float
    benchmark_ticker: str
    benchmark_entry_price: float | None = None  # captured at first valuation, buy-and-hold
    positions: dict[str, LanePosition] = field(default_factory=dict)

    @classmethod
    def fresh(cls, lane: str, *, initial_capital: float = 10_000.0,
              benchmark_ticker: str = "SPY") -> LaneBook:
        return cls(
            lane=lane, initial_capital=initial_capital, cash=initial_capital,
            benchmark_ticker=benchmark_ticker,
        )


@dataclass(frozen=True)
class TradeFill:
    """One executed (simulated) fill; realized_pnl is set on sells only."""

    lane: str
    executed_at: str
    ticker: str
    side: str  # "buy" | "sell"
    qty: float
    price: float  # effective fill price after slippage
    fees: float  # fee + slippage cost in currency
    reason: str
    realized_pnl: float | None = None


@dataclass(frozen=True)
class LaneValuation:
    lane: str
    created_at: str
    equity: float
    total_return: float
    cash: float
    open_positions: int
    benchmark_return: float | None  # None until a benchmark entry price is captured


def buy(
    book: LaneBook,
    ticker: str,
    price: float,
    executed_at: str,
    *,
    fraction: float,
    reason: str,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> tuple[LaneBook, TradeFill | None]:
    """Open a long position sized as `fraction` of current book value, capped by available
    cash: spend = min(cash, fraction * (cash + Σ qty*entry_price)). Positions count at
    their ENTRY price here — sizing must not depend on marks the caller may not have.
    Returns (book, None) when the ticker is already held, the price is invalid, or the
    spendable amount is dust (< 1 currency unit)."""
    if ticker in book.positions or price <= 0 or fraction <= 0:
        return book, None
    entry_value = sum(p.qty * p.entry_price for p in book.positions.values())
    spend = min(book.cash, fraction * (book.cash + entry_value))
    if spend < 1.0:
        return book, None
    effective = price * (1.0 + slippage_bps / 10_000.0)
    fees = spend * fee_bps / 10_000.0
    qty = (spend - fees) / effective
    slip_cost = qty * (effective - price)
    position = LanePosition(qty=qty, entry_price=effective, opened_at=executed_at)
    new_book = replace(
        book, cash=book.cash - spend, positions={**book.positions, ticker: position}
    )
    fill = TradeFill(
        lane=book.lane, executed_at=executed_at, ticker=ticker, side="buy",
        qty=qty, price=effective, fees=fees + slip_cost, reason=reason,
    )
    return new_book, fill


def sell(
    book: LaneBook,
    ticker: str,
    price: float,
    executed_at: str,
    *,
    reason: str,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
) -> tuple[LaneBook, TradeFill | None]:
    """Close the full position at `price` (long-only book: sells always flatten).
    Returns (book, None) when nothing is held or the price is invalid."""
    position = book.positions.get(ticker)
    if position is None or price <= 0:
        return book, None
    effective = price * (1.0 - slippage_bps / 10_000.0)
    proceeds_gross = position.qty * effective
    fees = proceeds_gross * fee_bps / 10_000.0
    proceeds = proceeds_gross - fees
    slip_cost = position.qty * (price - effective)
    realized = proceeds - position.qty * position.entry_price
    positions = {t: p for t, p in book.positions.items() if t != ticker}
    new_book = replace(book, cash=book.cash + proceeds, positions=positions)
    fill = TradeFill(
        lane=book.lane, executed_at=executed_at, ticker=ticker, side="sell",
        qty=position.qty, price=effective, fees=fees + slip_cost, reason=reason,
        realized_pnl=realized,
    )
    return new_book, fill


def mark_to_market(book: LaneBook, prices: dict[str, float]) -> float:
    """Current equity: cash + positions at the given prices; a position without a price
    is held at its entry price (cannot mark what we cannot see — honest, labelled)."""
    value = book.cash
    for ticker, position in book.positions.items():
        price = prices.get(ticker)
        value += position.qty * (price if price and price > 0 else position.entry_price)
    return value


def capture_benchmark(book: LaneBook, benchmark_price: float | None) -> LaneBook:
    """Record the buy-and-hold benchmark entry at the lane's FIRST observed price."""
    if book.benchmark_entry_price is not None or not benchmark_price or benchmark_price <= 0:
        return book
    return replace(book, benchmark_entry_price=benchmark_price)


def valuation(
    book: LaneBook,
    prices: dict[str, float],
    benchmark_price: float | None,
    created_at: str,
) -> LaneValuation:
    equity = mark_to_market(book, prices)
    benchmark_return = None
    if book.benchmark_entry_price and benchmark_price and benchmark_price > 0:
        benchmark_return = benchmark_price / book.benchmark_entry_price - 1.0
    return LaneValuation(
        lane=book.lane, created_at=created_at, equity=equity,
        total_return=equity / book.initial_capital - 1.0,
        cash=book.cash, open_positions=len(book.positions),
        benchmark_return=benchmark_return,
    )


def stats(trades: list[TradeFill | dict]) -> dict:
    """Realized-trade statistics for the arena table: sells carry the verdicts."""
    def _get(t, key):  # noqa: ANN001, ANN202 - accepts dataclass or storage dict rows
        return getattr(t, key, None) if not isinstance(t, dict) else t.get(key)

    sells = [t for t in trades if _get(t, "side") == "sell" and _get(t, "realized_pnl") is not None]
    wins = sum(1 for t in sells if _get(t, "realized_pnl") > 0)
    fees = sum(_get(t, "fees") or 0.0 for t in trades)
    return {
        "n_trades": len(sells),
        "n_fills": len(trades),
        "win_rate": wins / len(sells) if sells else None,
        "realized_pnl": sum(_get(t, "realized_pnl") for t in sells) if sells else 0.0,
        "fees_paid": fees,
    }
