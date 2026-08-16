"""Parameter search for the event lane's exit knobs (T10 of the 2026-08-16 plan).

Nico's goal: the system should learn from its own results instead of holding whatever numbers
were typed in once. The concrete trigger is a finding from the nightly lane review — 59 % of
the swing lane's result comes from positions timing out, not from the profit target being hit,
which says target and holding period are not tuned to each other.

WHAT THIS DOES: replay historical events with different exit rules and score each combination.
WHAT IT DOES NOT DO: change anything. Adoption is T12 and has its own hurdle; this module only
produces evaluated candidates.

Trades are simulated with the SAME `exits.exit_reason` the live lane uses, so a candidate that
wins here wins under the rule that will actually run. Re-implementing the exit logic for the
backtest is the classic way to tune a strategy that never existed.

Multiple testing is why this has its own ledger (`lane_trials`) rather than joining the ML or
the strategy pool: forty combinations tried against one dataset will always produce a winner,
and a hurdle only means something if it counts the trials that were actually run against THIS
question. Same separation v14 introduced for the rule strategies.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import pandas as pd

from equity_scout.exits import ExitRules, exit_reason

# The knobs the live swing lane exposes (st_swing.PROFIT_TARGET / STOP_LOSS /
# MAX_HOLDING_CALENDAR_DAYS). Values bracket today's settings rather than sprawling: a grid
# wide enough to contain any answer is a grid guaranteed to contain a lucky one.
PROFIT_TARGETS = (0.03, 0.05, 0.08, 0.12)
STOP_LOSSES = (0.02, 0.03, 0.05)
MAX_DAYS = (3, 7, 14)


@dataclass(frozen=True)
class LaneTrial:
    """One evaluated parameter set. `n_trades` travels with every metric on purpose — a mean
    over eleven trades and a mean over eleven hundred are not comparable numbers, and the
    champion registry learned that the expensive way on 2026-08-11."""

    profit_target: float
    stop_loss: float
    max_days: int
    n_trades: int
    mean_pnl_pct: float
    stdev_pnl_pct: float
    total_pnl_pct: float
    win_rate: float
    exit_mix: dict[str, int]

    @property
    def t_stat(self) -> float | None:
        """Against zero. Without this a comparison between two candidates is a comparison of
        two point estimates — which is how a champion held its title for five weeks on a
        sample of 220 rows (2026-08-11)."""
        if self.n_trades < 2 or self.stdev_pnl_pct <= 0:
            return None
        return self.mean_pnl_pct / (self.stdev_pnl_pct / (self.n_trades ** 0.5))

    @property
    def key(self) -> str:
        return f"pt{self.profit_target}_sl{self.stop_loss}_md{self.max_days}"


def simulate_event(closes: pd.Series, entry_index: int, rules: ExitRules) -> tuple[float, str]:
    """One trade: enter at `entry_index`, walk forward until an exit rule fires.

    Returns (return since entry, exit reason). A series that ends before any rule fires exits
    at the last observation and says so — silently dropping those would remove exactly the
    trades that ran longest.
    """
    entry_price = float(closes.iloc[entry_index])
    for offset in range(1, len(closes) - entry_index):
        price = float(closes.iloc[entry_index + offset])
        ret = price / entry_price - 1
        reason = exit_reason(ret, offset, rules)
        if reason:
            return ret, reason
    last = float(closes.iloc[-1]) / entry_price - 1
    return last, "Reihe zu Ende"


def evaluate(closes_by_ticker: dict[str, pd.Series], events: list[tuple[str, pd.Timestamp]],
             *, profit_target: float, stop_loss: float, max_days: int) -> LaneTrial:
    """Score one parameter set over all events."""
    rules = ExitRules(profit_target=profit_target, stop_loss=stop_loss, max_holding_days=max_days)
    returns: list[float] = []
    mix: dict[str, int] = {}
    for ticker, day in events:
        closes = closes_by_ticker.get(ticker)
        if closes is None or closes.empty:
            continue
        pos = closes.index.searchsorted(day)
        # The lane enters on the close AFTER the event, never on the event bar itself.
        if pos + 1 >= len(closes):
            continue
        ret, reason = simulate_event(closes, pos + 1, rules)
        returns.append(ret)
        short = reason.split("(")[0].strip()
        mix[short] = mix.get(short, 0) + 1
    n = len(returns)
    mean = (sum(returns) / n) if n else 0.0
    stdev = (sum((r - mean) ** 2 for r in returns) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return LaneTrial(
        profit_target=profit_target,
        stop_loss=stop_loss,
        max_days=max_days,
        n_trades=n,
        mean_pnl_pct=mean,
        stdev_pnl_pct=stdev,
        total_pnl_pct=sum(returns),
        win_rate=(sum(1 for r in returns if r > 0) / n) if n else 0.0,
        exit_mix=mix,
    )


def grid() -> list[tuple[float, float, int]]:
    """The full search space, in a fixed order — the cursor in the ledger indexes into this,
    so a reordering would silently re-evaluate the wrong cell."""
    return list(itertools.product(PROFIT_TARGETS, STOP_LOSSES, MAX_DAYS))


def search(closes_by_ticker: dict[str, pd.Series], events: list[tuple[str, pd.Timestamp]],
           *, limit: int | None = None, start: int = 0) -> list[LaneTrial]:
    """Evaluate the grid (or a slice of it, for the nightly budget)."""
    space = grid()
    if limit is not None:
        space = [space[i % len(space)] for i in range(start, start + limit)]
    return [
        evaluate(closes_by_ticker, events, profit_target=pt, stop_loss=sl, max_days=md)
        for pt, sl, md in space
    ]
