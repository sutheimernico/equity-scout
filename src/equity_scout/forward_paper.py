"""Forward paper trading: run a strategy *forward* in time as a persistent account.

The backtest (`engine.run_backtest`) replays a strategy over history. This module does the honest
inverse: a stateful `ForwardAccount` that is advanced one step at a time as new prices arrive, so a
real out-of-sample track record accumulates from today on. The strategy stays state-free — the same
`decide(as_of, market)` runs here as in the backtest; only the account carries state.

Each `advance_account` step: drift the held weights with the realised return since the last step
(same formula as the engine, marked to today's close), let the strategy pick new targets from data
strictly BEFORE today, charge cost on the turnover, and emit a valuation snapshot. The decision must
not see today's own close: `engine.run_backtest` never lets `decide` see the same day's close that
becomes the rebalance's execution price (its `MarketView(panel, date)` excludes `date` itself) — it
implicitly assumes a market-on-close order placed during the day, before today's close is known.
Feeding today's close into the decision here, then also using it as the execution price, would give
the forward account a one-day look-ahead edge the backtest never had, so the two would no longer be
comparable. Advancing twice on the same panel date is a no-op (idempotent), so a daily cron or a
manual run is safe to repeat.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

from equity_scout.exits import ExitRules, exit_reason
from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import Strategy, normalise_weights, turnover, weights_dict


@dataclass(frozen=True)
class PositionEntry:
    """Per-ticker entry tracking for a currently-held forward-paper position (plan v7, strand A2)
    — parallel to `weights`, not a replacement for the weight-based equity mechanic. Remembers
    what price/date a ticker was entered at, so `exits.exit_reason` has a return-since-entry and a
    holding period to check before each rebalance."""

    entry_price: float
    opened_at: str  # ISO date


@dataclass(frozen=True)
class ExitEvent:
    """One rules-triggered exit booked during an advance (plan v7, strand A2) — the persisted
    audit trail for why a ticker left the book (profit target / stop loss / max holding days)."""

    created_at: str  # ISO date the exit was booked (this advance's panel date)
    ticker: str
    entry_price: float
    exit_price: float
    opened_at: str  # ISO date the position was entered
    return_pct: float  # return since entry, sign-adjusted for short
    held_days: int
    reason: str  # German, from equity_scout.exits.exit_reason


@dataclass(frozen=True)
class ForwardAccount:
    """The accumulating state of one strategy run forward. `weights` are the post-rebalance targets
    set on `last_as_of`; they are drifted to the present at the next advance. `positions` tracks the
    entry price/date behind each currently-held ticker in `weights` — it never changes the weight
    mechanic itself, it only feeds the exit-rule check in `advance_account`."""

    strategy_name: str
    initial_capital: float
    equity: float
    benchmark_ticker: str
    benchmark_equity: float
    last_as_of: str | None  # ISO date of the last advance; None until first advanced
    weights: dict[str, float] = field(default_factory=dict)
    positions: dict[str, PositionEntry] = field(default_factory=dict)

    @classmethod
    def fresh(
        cls,
        strategy_name: str,
        *,
        initial_capital: float = 10_000.0,
        benchmark_ticker: str = "SPY",
    ) -> ForwardAccount:
        return cls(
            strategy_name=strategy_name,
            initial_capital=initial_capital,
            equity=initial_capital,
            benchmark_ticker=benchmark_ticker,
            benchmark_equity=initial_capital,
            last_as_of=None,
            weights={},
            positions={},
        )


@dataclass(frozen=True)
class ForwardValuation:
    created_at: str  # ISO date (the panel date this snapshot is for)
    equity: float
    total_return: float
    benchmark_equity: float
    benchmark_return: float
    exits: tuple[ExitEvent, ...] = ()  # rules-triggered exits booked this step (plan v7 A2)


def _price_on_or_before(series: pd.Series, date: pd.Timestamp) -> float | None:
    visible = series.loc[:date]
    return float(visible.iloc[-1]) if len(visible) else None


def _asset_return(
    closes: pd.DataFrame, ticker: str, start: pd.Timestamp, end: pd.Timestamp
) -> float | None:
    """Total return of `ticker` from the close on/before `start` to the close on/before `end`, or
    None when that return would not be honest (v13 R2 review): the ticker has no column at all, or
    there is no price row strictly newer than `start` on/before `end` — the "end" side would then
    resolve to the exact same stale reading as `start` (or an even earlier one), and reporting that
    as "0% return" fabricates a number instead of admitting there is no fresh reading yet. Callers
    must not silently treat None as 0.0 without a documented reason — see `_drift_return` below."""
    if ticker not in closes.columns:
        return None
    series = closes[ticker].dropna()
    visible_end = series.loc[:end]
    if len(visible_end) == 0 or visible_end.index[-1] <= start:
        return None
    p1 = float(visible_end.iloc[-1])
    p0 = _price_on_or_before(series, start)
    if p0 is None or p0 <= 0:
        return None
    return p1 / p0 - 1.0


def _drift_return(closes: pd.DataFrame, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Wraps `_asset_return` for forward_paper's own drift/benchmark arithmetic below: a stale or
    missing reading is treated as a 0% return — same as `_asset_return` did before it started
    distinguishing "no fresh price" from "0%" (v13 R2). Real stale-position handling here (marking
    the position, not the whole window) is the follow-up task v13 R4; until then this module's
    observable behaviour must not change."""
    r = _asset_return(closes, ticker, start, end)
    return 0.0 if r is None else r


# Daily short-borrow cost proxy in bps of short gross exposure (~2.5 %/yr). A PROXY by
# construction: free data has no real borrow rates or availability — every surface showing a
# short account must label this simplification (plan v6 P3).
BORROW_BPS_PER_DAY = 1.0


def advance_account(
    account: ForwardAccount,
    strategy: Strategy,
    panel: PricePanel,
    *,
    costs_bps: float = 10.0,
    borrow_bps_per_day: float = BORROW_BPS_PER_DAY,
    exit_rules: ExitRules = ExitRules(),
) -> tuple[ForwardAccount, ForwardValuation | None]:
    """Advance `account` to the latest panel date. Returns (account, valuation); valuation is None
    when the account is already current for that date (idempotent).

    Short support (signed weights, plan v6 P3): a negative weight earns when the asset falls
    (`w * r` with w < 0), pays a daily borrow-cost PROXY on its gross exposure, and the account has
    a simulated margin floor — equity at or below zero forces a full liquidation (weights cleared,
    equity floored at 0). Fills stay at close prices with no borrow-availability model; that is a
    labelled simplification, never real trading conditions.

    Trade lifecycle (plan v7, strand A2): before the strategy re-decides its targets, every
    currently-held ticker is checked against `exit_rules` (profit target / stop loss / max holding
    days, same thresholds as the arena lanes via `equity_scout.exits`). A ticker that trips a rule
    is closed and LOCKED OUT of re-entry for this same advance, even if the strategy's own
    `decide()` would pick it again right away — the strategies here are stateless and have no
    notion of "I just sold this", so the lockout has to live here instead."""
    if len(panel.dates) == 0:
        return account, None
    today = panel.dates[-1]
    last = pd.Timestamp(account.last_as_of) if account.last_as_of else None
    if last is not None and last >= today:
        return account, None  # already current — no new trading day to book
    if account.equity <= 0.0:
        return account, None  # margin-wiped — a dead account never trades again

    closes = panel.closes
    equity = account.equity
    benchmark_equity = account.benchmark_equity
    weights = dict(account.weights)
    entries = dict(account.positions)

    def _price_today(ticker: str) -> float | None:
        return _price_on_or_before(closes[ticker], today) if ticker in closes.columns else None

    # 1. Drift held weights + benchmark with the realised return since the last advance.
    if last is not None:
        port_return = sum(w * _drift_return(closes, t, last, today) for t, w in weights.items())
        equity *= 1.0 + port_return
        growth = 1.0 + port_return
        if growth > 0 and weights:
            weights = {
                t: w * (1.0 + _drift_return(closes, t, last, today)) / growth
                for t, w in weights.items()
            }
        benchmark_equity *= 1.0 + _drift_return(closes, account.benchmark_ticker, last, today)

        # 1b. Borrow-cost proxy on short gross exposure, per trading day since the last advance.
        short_gross = sum(-w for w in weights.values() if w < 0)
        if short_gross > 0 and borrow_bps_per_day > 0:
            n_days = int(((panel.dates > last) & (panel.dates <= today)).sum())
            equity *= 1.0 - short_gross * borrow_bps_per_day * n_days / 10_000.0

    # 1c. Simulated margin floor: a short book can lose more than the account. At or below zero
    # the account is force-liquidated — equity floors at 0 and stays there (no negative equity, no
    # further trading), so CAGR/Sharpe never compute on a negative base.
    if last is not None and equity <= 0.0:
        wiped = replace(
            account, equity=0.0, benchmark_equity=benchmark_equity,
            last_as_of=today.date().isoformat(), weights={}, positions={},
        )
        valuation = ForwardValuation(
            created_at=today.date().isoformat(),
            equity=0.0,
            total_return=-1.0,
            benchmark_equity=benchmark_equity,
            benchmark_return=benchmark_equity / account.initial_capital - 1.0,
        )
        return wiped, valuation

    # 1d. Apply exit rules to every currently held ticker BEFORE the rebalance (plan v7, strand
    # A2). The weight's sign (preserved through the drift above, since it only ever multiplies by
    # a non-negative factor) tells us the side: a short's return is the mirror image of a long's,
    # since a short profits when the price falls. A ticker without a current price is held
    # untouched — same stance as lanes.apply_exits (cannot judge a rule without a price).
    today_iso = today.date().isoformat()
    exit_events: list[ExitEvent] = []
    if last is not None:
        for ticker, entry in list(entries.items()):
            w = weights.get(ticker)
            if w is None:
                continue
            price = _price_today(ticker)
            if price is None or price <= 0 or entry.entry_price <= 0:
                continue  # no valid price on either side — cannot judge a rule, hold untouched
            sign = 1.0 if w >= 0 else -1.0
            return_pct = sign * (price - entry.entry_price) / entry.entry_price
            held_days = (today - pd.Timestamp(entry.opened_at)).days
            reason = exit_reason(return_pct, held_days, exit_rules)
            if reason is None:
                continue
            exit_events.append(
                ExitEvent(
                    created_at=today_iso, ticker=ticker, entry_price=entry.entry_price,
                    exit_price=price, opened_at=entry.opened_at, return_pct=return_pct,
                    held_days=held_days, reason=reason,
                )
            )
            del entries[ticker]
    blocked_today = {event.ticker for event in exit_events}

    # 2. Strategy decides new targets from data strictly BEFORE today — same convention as the
    # engine's MarketView(panel, date), which the backtest never lets peek at the rebalance day's
    # own close. The new targets still take effect (and get marked to market) at today's close on
    # the *next* advance; only the decision itself must not see it first. Anything exited above is
    # filtered out here — the strategies are stateless and would happily re-propose it.
    view = MarketView(panel, today)
    raw_targets = [tw for tw in strategy.decide(view.as_of, view) if tw.ticker not in blocked_today]
    targets = weights_dict(normalise_weights(raw_targets))

    # 3. Charge cost on the rebalance turnover (same convention as the engine). `weights` here
    # still includes anything force-exited above, so closing it is correctly priced as a full sell
    # (turnover |0 - w_old|), same cost as if the strategy had simply dropped it on its own.
    equity *= 1.0 - turnover(weights, targets) * costs_bps / 10_000.0

    # 4. Roll entry tracking forward: keep the original entry for anything still held, open a
    # fresh one (today's close) for anything newly added — including a ticker that just re-enters
    # after NOT being exited today (ordinary turnover, out of scope for the re-entry lock above).
    def _entry_for(ticker: str) -> PositionEntry:
        if ticker in entries:
            return entries[ticker]
        price = _price_today(ticker)
        return PositionEntry(entry_price=price if price is not None else 0.0, opened_at=today_iso)

    new_positions = {ticker: _entry_for(ticker) for ticker in targets}

    new_account = replace(
        account,
        equity=equity,
        benchmark_equity=benchmark_equity,
        last_as_of=today_iso,
        weights=targets,
        positions=new_positions,
    )
    valuation = ForwardValuation(
        created_at=today_iso,
        equity=equity,
        total_return=equity / account.initial_capital - 1.0,
        benchmark_equity=benchmark_equity,
        benchmark_return=benchmark_equity / account.initial_capital - 1.0,
        exits=tuple(exit_events),
    )
    return new_account, valuation
