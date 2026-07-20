"""The Auto-Depot engine (vision v10): one meta book over all strategy sleeves.

Look-through aggregation: each sleeve's `decide()` output is scaled by its meta weight
(`autotrader_allocator`) and summed per ticker — a long bot and a short bot on the same name
net out at the depot level, which is correct (the depot would not send offsetting orders).
The aggregated targets then pass the protection chain (`autotrader_protections`) before they
become the book.

Execution keeps `forward_paper`'s look-ahead-safe convention deliberately (decisions see
strictly < today via MarketView, fills at today's adjusted close, mark-to-market by weight
drift, costs on turnover, borrow proxy on net short exposure, simulated margin floor) — one
fill convention across the whole repo, so autotrader and sleeve track records stay comparable.

Per-position exits (profit target / stop loss / max holding, `exits.py`) act in the sleeves'
forward_paper BOOKS, not in `decide()` — strategies are stateless (v12 R5, review 2026-07-20).
The depot therefore mirrors each ML sleeve's POST-exit forward book via `sleeve_holdings`:
tickers that sleeve's book no longer holds are dropped from its contribution, and the freed
weight sits in cash (never redistributed — same honesty as the concentration cap). Rule
sleeves are broad-ETF allocators and pass through unfiltered; depot-level protection remains
the risk layer's job.

Trades are first-class records (per-ticker weight delta, notional, cost share). They are the
honest seam a future broker adapter would consume — no speculative interface beyond the data.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

from equity_scout.autotrader_allocator import SleeveAllocation
from equity_scout.autotrader_protections import (
    BreakerState,
    ProtectionRule,
    RiskContext,
    RiskEvent,
    apply_protections,
    default_protections,
)

# Shared fill/return arithmetic — module-private by name, but reusing it is the point:
# the cost and return conventions must not drift between the sleeves and the depot.
from equity_scout.forward_paper import BORROW_BPS_PER_DAY, _asset_return
from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import Strategy, normalise_weights, turnover, weights_dict

TRADE_EPS = 1e-6  # weight deltas below this are float noise, not trades


@dataclass(frozen=True)
class TradeRecord:
    """One booked (simulated) trade: the signed weight change and its USD notional/cost."""

    created_at: str  # ISO date
    ticker: str
    delta_weight: float  # signed: + buys/covers toward long, - sells/shorts
    notional: float  # |delta_weight| * equity at rebalance, USD
    cost: float  # this trade's share of the turnover cost, USD


@dataclass(frozen=True)
class AutoDepotAccount:
    """The accumulating state of the one auto-traded depot. `weights` are the post-rebalance
    per-ticker targets set on `last_as_of`; `peak_equity` and `breaker` carry the drawdown
    breaker's memory; `sleeve_weights`/`sleeve_mode` remember the meta allocation last applied
    (display + audit, the allocator recomputes monthly)."""

    initial_capital: float
    equity: float
    benchmark_ticker: str
    benchmark_equity: float
    peak_equity: float
    last_as_of: str | None
    weights: dict[str, float] = field(default_factory=dict)
    breaker: BreakerState = BreakerState()
    sleeve_weights: dict[str, float] = field(default_factory=dict)
    sleeve_mode: str = "anchor"

    @classmethod
    def fresh(
        cls, *, initial_capital: float = 100_000.0, benchmark_ticker: str = "SPY"
    ) -> AutoDepotAccount:
        return cls(
            initial_capital=initial_capital,
            equity=initial_capital,
            benchmark_ticker=benchmark_ticker,
            benchmark_equity=initial_capital,
            peak_equity=initial_capital,
            last_as_of=None,
        )


@dataclass(frozen=True)
class AutoDepotValuation:
    created_at: str
    equity: float
    total_return: float
    benchmark_equity: float
    benchmark_return: float
    gross_exposure: float
    drawdown: float
    equity_eur: float | None = None  # None when the FX fetch failed — never invented
    fx_rate: float | None = None  # EUR per 1 USD at valuation time
    trades: tuple[TradeRecord, ...] = ()
    risk_events: tuple[RiskEvent, ...] = ()


def aggregate_targets(
    allocation: SleeveAllocation, decisions: dict[str, list]
) -> dict[str, float]:
    """Look-through: sleeve meta weight x sleeve's own (normalised, signed) target weights,
    summed per ticker. Sleeves in the allocation without a decision contribute nothing (an
    empty decide = that sleeve sits in cash)."""
    aggregated: dict[str, float] = {}
    for sleeve, meta_weight in allocation.weights.items():
        sleeve_targets = weights_dict(normalise_weights(decisions.get(sleeve, [])))
        for ticker, weight in sleeve_targets.items():
            aggregated[ticker] = aggregated.get(ticker, 0.0) + meta_weight * weight
    return {t: w for t, w in aggregated.items() if abs(w) > TRADE_EPS}


def advance_depot(
    account: AutoDepotAccount,
    strategies: list[Strategy],
    allocation: SleeveAllocation,
    panel: PricePanel,
    *,
    protections: list[ProtectionRule] | None = None,
    regime_level: str | None = None,
    depot_returns: pd.Series | None = None,
    fx_rate: float | None = None,
    costs_bps: float = 10.0,
    borrow_bps_per_day: float = BORROW_BPS_PER_DAY,
    sleeve_holdings: dict[str, set[str]] | None = None,
) -> tuple[AutoDepotAccount, AutoDepotValuation | None]:
    """Advance the depot to the latest panel date. Returns (account, valuation); valuation is
    None when already current for that date (idempotent — safe to re-run in a cron chain).

    Step order: drift -> margin floor -> drawdown/peak update -> sleeve decisions (strictly
    pre-today data) -> look-through aggregation -> protection chain -> turnover cost + trades.
    """
    if len(panel.dates) == 0:
        return account, None
    today = panel.dates[-1]
    last = pd.Timestamp(account.last_as_of) if account.last_as_of else None
    if last is not None and last >= today:
        return account, None
    if account.equity <= 0.0:
        return account, None  # margin-wiped — a dead depot never trades again

    closes = panel.closes
    equity = account.equity
    benchmark_equity = account.benchmark_equity
    weights = dict(account.weights)
    today_iso = today.date().isoformat()

    # 1. Drift held weights + benchmark with the realised return since the last advance
    #    (same arithmetic as forward_paper.advance_account).
    if last is not None:
        port_return = sum(w * _asset_return(closes, t, last, today) for t, w in weights.items())
        equity *= 1.0 + port_return
        growth = 1.0 + port_return
        if growth > 0 and weights:
            weights = {
                t: w * (1.0 + _asset_return(closes, t, last, today)) / growth
                for t, w in weights.items()
            }
        benchmark_equity *= 1.0 + _asset_return(closes, account.benchmark_ticker, last, today)

        short_gross = sum(-w for w in weights.values() if w < 0)
        if short_gross > 0 and borrow_bps_per_day > 0:
            n_days = int(((panel.dates > last) & (panel.dates <= today)).sum())
            equity *= 1.0 - short_gross * borrow_bps_per_day * n_days / 10_000.0

    if last is not None and equity <= 0.0:
        wiped = replace(
            account, equity=0.0, benchmark_equity=benchmark_equity,
            last_as_of=today_iso, weights={},
        )
        valuation = AutoDepotValuation(
            created_at=today_iso, equity=0.0, total_return=-1.0,
            benchmark_equity=benchmark_equity,
            benchmark_return=benchmark_equity / account.initial_capital - 1.0,
            gross_exposure=0.0, drawdown=1.0, fx_rate=fx_rate,
            equity_eur=0.0 if fx_rate is not None else None,
        )
        return wiped, valuation

    # 2. Drawdown context for the breaker: peak includes today's marked equity, so a fresh
    #    high reads as zero drawdown.
    peak_equity = max(account.peak_equity, equity)
    drawdown = max(0.0, 1.0 - equity / peak_equity) if peak_equity > 0 else 0.0

    # 3. Sleeve decisions from data strictly BEFORE today, aggregated look-through.
    #    ML sleeves are mirrored against their POST-exit forward book (module docstring).
    view = MarketView(panel, today)
    decisions = {s.name: s.decide(view.as_of, view) for s in strategies}
    if sleeve_holdings:
        decisions = {
            name: (
                [tw for tw in targets if tw.ticker in sleeve_holdings[name]]
                if name in sleeve_holdings else targets
            )
            for name, targets in decisions.items()
        }
    raw_targets = aggregate_targets(allocation, decisions)

    # 4. Protection chain (may mutate ctx.breaker — the account persists it).
    ctx = RiskContext(
        as_of=today, regime_level=regime_level, depot_returns=depot_returns,
        drawdown=drawdown, breaker=account.breaker,
    )
    chain = default_protections() if protections is None else protections
    targets, risk_events = apply_protections(raw_targets, chain, ctx)
    targets = {t: w for t, w in targets.items() if abs(w) > TRADE_EPS}

    # 5. Turnover cost, attributed to per-ticker trade records.
    total_turnover = turnover(weights, targets)
    total_cost = equity * total_turnover * costs_bps / 10_000.0
    trades: list[TradeRecord] = []
    for ticker in sorted(set(weights) | set(targets)):
        delta = targets.get(ticker, 0.0) - weights.get(ticker, 0.0)
        if abs(delta) <= TRADE_EPS:
            continue
        trades.append(
            TradeRecord(
                created_at=today_iso,
                ticker=ticker,
                delta_weight=delta,
                notional=abs(delta) * equity,
                cost=total_cost * abs(delta) / total_turnover if total_turnover > 0 else 0.0,
            )
        )
    equity -= total_cost

    new_account = replace(
        account,
        equity=equity,
        benchmark_equity=benchmark_equity,
        peak_equity=max(peak_equity, equity),
        last_as_of=today_iso,
        weights=targets,
        breaker=ctx.breaker,
        sleeve_weights=dict(allocation.weights),
        sleeve_mode=allocation.mode,
    )
    valuation = AutoDepotValuation(
        created_at=today_iso,
        equity=equity,
        total_return=equity / account.initial_capital - 1.0,
        benchmark_equity=benchmark_equity,
        benchmark_return=benchmark_equity / account.initial_capital - 1.0,
        gross_exposure=sum(abs(w) for w in targets.values()),
        drawdown=drawdown,
        equity_eur=equity * fx_rate if fx_rate is not None else None,
        fx_rate=fx_rate,
        trades=tuple(trades),
        risk_events=tuple(risk_events),
    )
    return new_account, valuation
