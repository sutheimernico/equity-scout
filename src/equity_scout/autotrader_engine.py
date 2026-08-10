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

import logging
import sys
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
from equity_scout.costs import fill_cost_rate_bps

# Shared fill/return arithmetic — module-private by name, but reusing it is the point:
# the cost and return conventions must not drift between the sleeves and the depot.
from equity_scout.forward_paper import BORROW_BPS_PER_DAY, _asset_return
from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import Strategy, normalise_weights, weights_dict

logger = logging.getLogger(__name__)

TRADE_EPS = 1e-6  # weight deltas below this are float noise, not trades


@dataclass(frozen=True)
class TradeRecord:
    """One booked (simulated) trade: the signed weight change and its USD notional/cost.
    Since v13 O2 a trade is decided on one advance and FILLED on the next: `decided_as_of`
    is the decision date, `created_at` the fill date, `fill` says which price actually
    filled it ("open", or "close_fallback" when no same-day open was available — lane
    fund-share series and feed gaps have no opens), `fill_price` that price. Rows from
    before v13 carry fill="close" (decided and filled on the same close)."""

    created_at: str  # ISO date (fill date)
    ticker: str
    delta_weight: float  # signed: + buys/covers toward long, - sells/shorts
    notional: float  # |delta_weight| * equity at rebalance, USD
    cost: float  # this trade's share of the turnover cost, USD
    fill: str = "close"  # "open" | "close_fallback" | "close" (pre-v13 rows)
    fill_price: float | None = None
    decided_as_of: str | None = None


@dataclass(frozen=True)
class PendingOrders:
    """The rebalance one advance decided and the next one fills (v13 O2): the full
    post-protection target book, not deltas — the fill computes deltas against the
    then-current drifted weights, so overnight drift cannot double-trade."""

    decided_as_of: str  # ISO date of the advance that computed these targets
    targets: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AutoDepotAccount:
    """The accumulating state of the one auto-traded depot. `weights` are the post-rebalance
    per-ticker targets set on `last_as_of`; `peak_equity` and `breaker` carry the drawdown
    breaker's memory; `sleeve_weights`/`sleeve_mode` remember the meta allocation last applied
    (display + audit, the allocator recomputes monthly). `last_marks` is the per-position
    valuation mark (v13 R2) each held ticker was last actually priced at — `{ticker: (date_iso,
    price)}` — so the NEXT advance can tell a fresh price from a stale repeat of the same window
    resolution (see `advance_depot`'s drift step)."""

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
    promoted_lanes: tuple[str, ...] = ()  # arena lanes currently earning depot capital (v12 I3)
    last_marks: dict[str, tuple[str, float]] = field(default_factory=dict)
    # The rebalance decided on last_as_of, waiting to fill at the next advance's open
    # (v13 O2). None = nothing pending (fresh account, or a pre-v13 blob).
    pending_orders: PendingOrders | None = None

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


def _resolved_price(
    closes: pd.DataFrame, ticker: str, as_of: pd.Timestamp
) -> tuple[pd.Timestamp, float] | None:
    """The latest close on/before `as_of`, WITH its own date — `_asset_return`'s window helper
    only returns the price, but the per-position marks below (v13 R2) need the date to tell a
    fresh reading apart from a stale repeat of the same row."""
    if ticker not in closes.columns:
        return None
    series = closes[ticker].dropna()
    visible = series.loc[:as_of]
    if len(visible) == 0:
        return None
    return visible.index[-1], float(visible.iloc[-1])


def _mark_return(
    closes: pd.DataFrame,
    ticker: str,
    last: pd.Timestamp,
    today: pd.Timestamp,
    mark: tuple[str, float] | None,
) -> tuple[float, tuple[str, float] | None]:
    """One held ticker's return for this advance, valued from its persisted mark rather than a
    re-resolved [last, today] window (v13 R2, the actual P0 fix): the window's on/before
    resolution on BOTH ends can land on the same stale row over and over and silently lose a real
    move for good the moment a fresh price finally lands between two advances (verified reviewer
    repro: a lane's equity jumped 10300 -> 15000 in one day and the depot booked 0.00 every night
    after, because both ends kept re-resolving to the pre-jump price).

    No mark yet (legacy account blob, or a ticker that only entered the book on a stale-price
    advance) falls back to the old window return so migration stays a no-op. A mark WITH no
    reading strictly newer than its own date carries the position at 0 this step and keeps the
    OLD mark untouched, so the full move books on the next advance that does see a fresh price —
    nothing is ever silently lost, it just books one advance later than it would with live data.
    """
    if mark is None:
        r = _asset_return(closes, ticker, last, today)
        resolved = _resolved_price(closes, ticker, today)
        new_mark = (resolved[0].date().isoformat(), resolved[1]) if resolved else None
        return (0.0 if r is None else r), new_mark

    mark_date, mark_price = pd.Timestamp(mark[0]), mark[1]
    resolved = _resolved_price(closes, ticker, today)
    if resolved is not None and resolved[0] > mark_date and mark_price > 0:
        date, price = resolved
        return price / mark_price - 1.0, (date.date().isoformat(), price)
    return 0.0, mark  # no fresher reading than the mark yet — hold at 0, keep the mark as-is


def _fill_price(
    ohlc: dict[str, pd.DataFrame] | None,
    closes: pd.DataFrame,
    ticker: str,
    today: pd.Timestamp,
) -> tuple[float | None, str]:
    """Price a pending order fills at on `today` (v13 O2). The day's OPEN when the OHLC
    world has one AND the close panel has a same-day close (the intraday attribution in
    `advance_depot` needs both ends); otherwise the latest resolved close as an honest,
    labelled fallback — lane fund-share tickers and feed gaps have no opens. (None,
    "close_fallback") when no price exists at all: the weight still rebalances (the book
    is weight-based) but the row says no real price backed it."""
    resolved = _resolved_price(closes, ticker, today)
    frame = ohlc.get(ticker) if ohlc else None
    if (
        frame is not None
        and today in frame.index
        and pd.notna(frame.at[today, "open"])
        and resolved is not None
        and resolved[0] == today
    ):
        return float(frame.at[today, "open"]), "open"
    return (resolved[1] if resolved else None), "close_fallback"


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
    ohlc: dict[str, pd.DataFrame] | None = None,
) -> tuple[AutoDepotAccount, AutoDepotValuation | None]:
    """Advance the depot to the latest panel date. Returns (account, valuation); valuation is
    None when already current for that date (idempotent — safe to re-run in a cron chain).

    Fill convention since v13 O2: an advance no longer fills its own rebalance at the same
    close it decided on (that was the documented look-ahead caveat). Instead it FIRST fills
    the previous advance's `pending_orders` at today's open (from the `ohlc` world; honest
    close fallback when no open exists), then decides new targets and persists them as the
    next pending orders. Costs book at fill time. Economically the filled deltas participate
    from the open: the drift step values the OLD book close-to-close, and the intraday
    attribution term `sum(delta * (close/open - 1))` moves the fill-day's open-to-close leg
    onto the new deltas — first-order exact, same linearisation as the drift sum itself.
    Valuation marks (v13 R2) are untouched: marks track close-based valuation, fills track
    execution.

    Step order: drift (per-position marks, v13 R2) -> margin floor -> drawdown/peak update ->
    fill pending orders (open fill + costs + intraday attribution) -> sleeve decisions
    (strictly pre-today data) -> look-through aggregation -> protection chain -> persist as
    new pending orders -> roll marks forward for the filled book.
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
    marks_after_drift = dict(account.last_marks)  # updated below; falls through unchanged if
    # `last is None` (fresh account — nothing was held yet to have a mark)
    today_iso = today.date().isoformat()

    # 1. Drift held weights + benchmark with the realised return since the last advance
    #    (same arithmetic as forward_paper.advance_account). Each held ticker's return comes
    #    from its persisted valuation mark, not a re-resolved [last, today] window (v13 R2 — see
    #    `_mark_return`'s docstring for the bug this fixes). The benchmark is not a depot
    #    position and keeps the old window convention.
    if last is not None:
        asset_returns: dict[str, float] = {}
        marks_after_drift = {}
        uninitialised = 0
        for t in weights:
            r, new_mark = _mark_return(closes, t, last, today, account.last_marks.get(t))
            asset_returns[t] = r
            if new_mark is not None:
                marks_after_drift[t] = new_mark
            if t not in account.last_marks:
                uninitialised += 1
        if uninitialised:
            logger.info("mark init for %d positions", uninitialised)

        port_return = sum(w * asset_returns[t] for t, w in weights.items())
        equity *= 1.0 + port_return
        growth = 1.0 + port_return
        if growth > 0 and weights:
            weights = {
                t: w * (1.0 + asset_returns[t]) / growth
                for t, w in weights.items()
            }
        benchmark_equity *= 1.0 + (
            _asset_return(closes, account.benchmark_ticker, last, today) or 0.0
        )

        short_gross = sum(-w for w in weights.values() if w < 0)
        if short_gross > 0 and borrow_bps_per_day > 0:
            n_days = int(((panel.dates > last) & (panel.dates <= today)).sum())
            equity *= 1.0 - short_gross * borrow_bps_per_day * n_days / 10_000.0

    if last is not None and equity <= 0.0:
        wiped = replace(
            account, equity=0.0, benchmark_equity=benchmark_equity,
            last_as_of=today_iso, weights={}, last_marks={}, pending_orders=None,
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

    # 2b. Fill the PREVIOUS advance's pending orders at today's open (v13 O2). Deltas are
    #     computed against the drifted weights, so overnight drift never double-trades.
    #     Filled deltas get the fill-day's open-to-close leg via the attribution term —
    #     see the docstring; marks stay close-based and start at today's close for new
    #     positions, so nothing is double-counted.
    trades: list[TradeRecord] = []
    if account.pending_orders is not None:
        pending = account.pending_orders
        fill_targets = {t: w for t, w in pending.targets.items() if abs(w) > TRADE_EPS}
        total_cost = 0.0
        intraday_attribution = 0.0
        for ticker in sorted(set(weights) | set(fill_targets)):
            delta = fill_targets.get(ticker, 0.0) - weights.get(ticker, 0.0)
            if abs(delta) <= TRADE_EPS:
                continue
            price, fill_kind = _fill_price(ohlc, closes, ticker, today)
            if fill_kind == "close_fallback":
                logger.warning(
                    "pending order %s filled at close fallback (no open for %s)",
                    ticker, today_iso,
                )
            elif price and price > 0:
                today_close = _resolved_price(closes, ticker, today)
                if today_close is not None:  # guaranteed by _fill_price's open branch
                    intraday_attribution += delta * (today_close[1] / price - 1.0)
            # v13 O3: per-ticker liquidity-aware cost, max(flat floor, half CS spread).
            # LOWER BOUND — see equity_scout.costs; `costs_bps` stays the floor. The
            # frame is cut at `today`: a live OHLC fetch can carry a still-running
            # session's row (Tokyo at 02:35), which is not a completed day's range.
            frame = ohlc.get(ticker) if ohlc else None
            rate_bps = fill_cost_rate_bps(
                frame.loc[:today] if frame is not None else None, flat_bps=costs_bps
            )
            cost = abs(delta) * equity * rate_bps / 10_000.0
            total_cost += cost
            trades.append(
                TradeRecord(
                    created_at=today_iso,
                    ticker=ticker,
                    delta_weight=delta,
                    notional=abs(delta) * equity,
                    cost=cost,
                    fill=fill_kind,
                    fill_price=price,
                    decided_as_of=pending.decided_as_of,
                )
            )
        weights = fill_targets
        equity *= 1.0 + intraday_attribution
        equity -= total_cost

    # 3. Sleeve decisions from data strictly BEFORE today, aggregated look-through.
    #    ML sleeves are mirrored against their POST-exit forward book (module docstring).
    #    Isolated per sleeve: a crashing decide() (bad feature layout, a data edge case) must
    #    not take the other, healthy sleeves down with it. A failed sleeve is EXCLUDED from
    #    `decisions` for today — `aggregate_targets` below already treats an absent key as
    #    "that sleeve sits in cash" (see its docstring), the exact same fate a legitimate empty
    #    decide() gets, so a crash costs that one sleeve's slice of the book, not everyone
    #    else's. The alternative — replaying the sleeve's last successful weights — has no home
    #    to live in: strategies are deliberately stateless (base.py, "no account-state
    #    parameter", v12 R5) and no per-sleeve target-weight history is persisted on
    #    `AutoDepotAccount` to replay from, so it would need new state rather than reusing an
    #    existing, already-safe contract.
    view = MarketView(panel, today)
    decisions: dict[str, list] = {}
    for s in strategies:
        try:
            decisions[s.name] = s.decide(view.as_of, view)
        except Exception as err:  # noqa: BLE001 - one sleeve's bug must not sink the others
            print(
                f"Sleeve {s.name} fehlgeschlagen: {err} — für {today_iso} "
                "übersprungen (Cash).",
                file=sys.stderr,
            )
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

    # 5. Persist today's decision as the NEXT advance's pending orders (v13 O2): no fill,
    #    no cost today — the trade happens at tomorrow's open, priced and charged then.
    new_pending = PendingOrders(decided_as_of=today_iso, targets=targets)

    # 6. Roll marks forward for the FILLED book (v13 R2): anything still held keeps the mark
    #    the drift step above just resolved for it (fresh price -> updated; stale -> the same
    #    old mark, unchanged, per `_mark_return`). Anything the fill just added for the first
    #    time gets a fresh mark at today's close — the intraday attribution already booked its
    #    open-to-close leg, so the mark taking over from the close double-counts nothing.
    #    Anything no longer held is dropped, so a re-entered ticker later starts clean.
    final_marks: dict[str, tuple[str, float]] = {}
    for t in weights:
        if t in marks_after_drift:
            final_marks[t] = marks_after_drift[t]
        else:
            resolved = _resolved_price(closes, t, today)
            if resolved is not None:
                final_marks[t] = (resolved[0].date().isoformat(), resolved[1])

    new_account = replace(
        account,
        equity=equity,
        benchmark_equity=benchmark_equity,
        peak_equity=max(peak_equity, equity),
        last_as_of=today_iso,
        weights=weights,
        breaker=ctx.breaker,
        sleeve_weights=dict(allocation.weights),
        sleeve_mode=allocation.mode,
        last_marks=final_marks,
        pending_orders=new_pending,
    )
    valuation = AutoDepotValuation(
        created_at=today_iso,
        equity=equity,
        total_return=equity / account.initial_capital - 1.0,
        benchmark_equity=benchmark_equity,
        benchmark_return=benchmark_equity / account.initial_capital - 1.0,
        gross_exposure=sum(abs(w) for w in weights.values()),
        drawdown=drawdown,
        equity_eur=equity * fx_rate if fx_rate is not None else None,
        fx_rate=fx_rate,
        trades=tuple(trades),
        risk_events=tuple(risk_events),
    )
    return new_account, valuation
