"""Triple-barrier meta-labels (López de Prado, AFML ch. 3).

For each event date where a primary signal says "go long", look forward over a horizon and ask: was
following it right? Label 1 if the upper (profit) barrier is touched before the lower (stop) barrier,
0 if the stop is hit first, and the sign of the final return if only the time barrier is reached.
This binary "should we have followed?" is the meta-label the model learns to predict — pure and
fully testable on a synthetic price path.
"""
from __future__ import annotations

import pandas as pd


def triple_barrier_labels(
    prices: pd.Series,
    events: pd.DatetimeIndex,
    *,
    horizon_days: int = 21,
    profit_take: float = 0.05,
    stop_loss: float = 0.05,
) -> pd.Series:
    """Label each event 1 (following the long signal worked) or 0 (it didn't).

    `prices` is a single asset's price series; `events` are dates the primary signal fired. Barriers
    are return fractions. Events without a forward window are dropped. Look-ahead-safe by design: the
    label uses only prices *after* the event, and is attached to the event date for training where
    purging/embargo then prevent leakage into the model.
    """
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
        else:  # only the time barrier was reached → sign of the final return
            labels[event] = int(returns.iloc[-1] > 0)
    return pd.Series(labels, dtype="int64")
