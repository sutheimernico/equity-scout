"""Triple-barrier labels (López de Prado, AFML ch. 3).

For each event date, look forward over a horizon and ask: was the upper (profit) barrier touched
before the lower (stop) barrier? Two callers use this with different `on_timeout` policies:
  * the meta-model's meta-labels ("was following the primary long signal right?") resolve a timeout
    (neither barrier touched) to the sign of the final return — `on_timeout="sign"`, the default.
  * the `entry_tb` model family's entry labels ("did the stock reach ITS OWN price target before
    its stop?") resolve a timeout to 0 — `on_timeout="zero"` — because an inconclusive timeout is a
    miss for that question, not a coin flip on the drift.
This binary label is the pure, fully-testable core both callers build on.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def triple_barrier_labels(
    prices: pd.Series,
    events: pd.DatetimeIndex,
    *,
    horizon_days: int = 21,
    profit_take: float = 0.05,
    stop_loss: float = 0.05,
    on_timeout: str = "sign",
) -> pd.Series:
    """Label each event 1 (profit barrier touched first) or 0 (stop barrier touched first, or —
    depending on `on_timeout` — neither touched within the horizon).

    `prices` is a single asset's price series; `events` are dates a label is wanted for. Barriers
    are return fractions (`profit_take`/`stop_loss`; both scalars — for per-event, vol-scaled
    barriers call this once per event with that event's own fractions, see
    `entry_eval.triple_barrier_entry_label`). Events without a forward window are dropped.
    Look-ahead-safe by design: the label uses only prices *after* the event, and is attached to the
    event date for training where purging/embargo then prevent leakage into the model.

    `on_timeout` decides the label when NEITHER barrier is touched by the time barrier: "sign"
    (default) resolves it to the sign of the final return (the meta-model's original behaviour);
    "zero" always labels a timeout 0 (the entry_tb family — see the module docstring).
    """
    if on_timeout not in ("sign", "zero"):
        raise ValueError(f"on_timeout must be 'sign' or 'zero', got {on_timeout!r}")
    labels: dict[pd.Timestamp, int] = {}
    for event in events:
        if event not in prices.index:
            continue
        forward = prices.loc[event:].iloc[1 : horizon_days + 1]
        if forward.empty:
            continue
        entry = float(prices.loc[event])
        if entry <= 0:
            continue
        returns = forward / entry - 1.0
        hit_up = returns.index[returns >= profit_take]
        hit_down = returns.index[returns <= -stop_loss]
        first_up = hit_up[0] if len(hit_up) else None
        first_down = hit_down[0] if len(hit_down) else None
        if first_up is not None and (first_down is None or first_up <= first_down):
            labels[event] = 1
        elif first_down is not None:
            labels[event] = 0
        elif on_timeout == "zero":
            labels[event] = 0
        else:  # only the time barrier was reached → sign of the final return
            labels[event] = int(returns.iloc[-1] > 0)
    return pd.Series(labels, dtype="int64")


def trailing_daily_vol(prices: pd.Series, *, window: int = 60) -> pd.Series:
    """Trailing realized daily-return volatility: rolling std of daily pct-change over `window`
    trailing trading days, NOT annualized — the barriers this feeds (`BarrierConfig`) are themselves
    daily-return fractions, so no annualization factor belongs here. 60 trading days (~3 months) is
    the default window: long enough to smooth out single-day noise, short enough to track a real
    volatility-regime change within a quarter. NaN wherever fewer than `window` trailing returns are
    available (start of the series)."""
    return prices.pct_change().rolling(window=window, min_periods=window).std(ddof=1)


@dataclass(frozen=True)
class BarrierConfig:
    """Volatility-scaled triple-barrier preset for the `entry_tb` model family — a config, not
    magic numbers baked into a label call. The profit/stop barriers are `k_pt`/`k_sl` multiples of
    the ticker's OWN trailing daily-return volatility (`trailing_daily_vol`, over `vol_window`
    trailing days), not fixed fractions — so a volatile stock gets wider barriers than a calm one.

    Persisted verbatim (`as_dict()`) into the registry's `metrics_json` under "barrier_config" so a
    follow-up task can reconstruct `price_target = price * (1 + k_pt * sigma)` and
    `stop = price * (1 - k_sl * sigma)` from the champion's own stored config — never re-derived
    from hardcoded defaults, which could silently drift from what the champion was actually trained
    on."""

    k_pt: float = 2.0
    k_sl: float = 1.0
    horizon_days: int = 40
    vol_window: int = 60

    def as_dict(self) -> dict:
        return {
            "k_pt": self.k_pt,
            "k_sl": self.k_sl,
            "horizon_days": self.horizon_days,
            "vol_window": self.vol_window,
        }
