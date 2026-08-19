"""Calendar-block bootstrap for pooled matrix cells (v16, 2026-08-19).

## Why this replaces the pooled t

`grid.pool_cells` computes `sum(t_i * sqrt(n_i)) / sqrt(sum(n_i))` and its docstring claims this
"never assumes the tickers are independent". That claim is false, and it is the reason the
hold-out has stayed shut since 2026-08-18: the formula IS the independence assumption. Stouffer
combination is only valid for independent test statistics.

The tickers are not independent — they share market-wide moves. When a signal fires on 70 names
on the same day, that is close to ONE observation of a market move, not 70. The inflation factor
for k equally correlated series is sqrt(1 + (k-1)*rho): at k=70 and rho=0.3 the pooled t comes
out about 4.7x too large. Every cell would look spectacular.

## What this does instead

Resample whole CALENDAR BLOCKS of trades with replacement (moving-block bootstrap, Künsch 1989;
the standard remedy for dependent data). Two properties make it the right tool here:

1. **Cross-sectional dependence is preserved by construction.** All trades inside a block stay
   together, so if 70 tickers fired on the same day they are resampled as the single event they
   effectively are. Nothing has to be assumed about the correlation structure — it is carried
   along in the data.
2. **Serial dependence within a block is preserved too**, which matters because momentum and
   mean-reversion signals cluster in time (a volatile month fires far more often than a calm one).

The output is a bootstrap distribution of the pooled mean net return. From it: a standard error
that reflects the real dependence, a bootstrap t, and a one-sided p-value. These replace the
Stouffer number for any cell that wants to qualify as a finding.

## Cost and scope

A bootstrap over every cell in the full grid would be prohibitive. It is therefore applied where
it decides something: the plateau CANDIDATES, re-measured before the hold-out is opened. That is
exactly the order the 2026-08-18 upgrade plan asks for.

Deterministic by seed, so a reported number can be reproduced exactly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_DRAWS = 2_000
DEFAULT_SEED = 20260819
MIN_BLOCKS = 8  # below this the bootstrap distribution is itself noise, not an estimate


@dataclass(frozen=True)
class BootstrapResult:
    """Pooled statistics that survive dependence between tickers and over time.

    `t` and `p_value` are None when the sample cannot support an estimate (too few calendar
    blocks). A None here means "not measurable", never "not significant" — the caller must not
    silently read it as a rejection.
    """

    n_trades: int
    n_blocks: int
    mean_net_bp: float | None
    std_error_bp: float | None
    t: float | None
    p_value: float | None
    ci_low_bp: float | None
    ci_high_bp: float | None
    naive_t: float | None          # what an independence-assuming test would have said
    inflation_factor: float | None  # naive_t / bootstrap t — the size of the lie

    def as_dict(self) -> dict:
        return {
            "n_trades": self.n_trades, "n_blocks": self.n_blocks,
            "mean_net_bp": self.mean_net_bp, "std_error_bp": self.std_error_bp,
            "t": self.t, "p_value": self.p_value,
            "ci_low_bp": self.ci_low_bp, "ci_high_bp": self.ci_high_bp,
            "naive_t": self.naive_t, "inflation_factor": self.inflation_factor,
        }


def block_key(timestamps: pd.DatetimeIndex, *, block: str = "M") -> np.ndarray:
    """Map trade timestamps to calendar-block labels.

    Month is the default because it is long enough to contain a full mean-reversion cycle on the
    daily scale while still leaving ~80 blocks over seven years. For minute-scale slices a
    caller may pass "W" — but never anything shorter than the holding period, or the blocks stop
    being independent of each other and the bootstrap understates the error again.
    """
    # tz dropped deliberately before to_period: a calendar month is a wall-clock concept and
    # pandas warns when converting a tz-aware index. The block label is identical either way.
    naive = timestamps.tz_localize(None) if timestamps.tz is not None else timestamps
    return naive.to_period(block).astype(str).to_numpy()


def block_bootstrap(
    net_bp: np.ndarray,
    timestamps: pd.DatetimeIndex,
    *,
    draws: int = DEFAULT_DRAWS,
    seed: int = DEFAULT_SEED,
    block: str = "M",
    min_blocks: int = MIN_BLOCKS,
) -> BootstrapResult:
    """Pooled mean net return with a dependence-aware standard error.

    `net_bp` and `timestamps` are the trades of ONE cell across ALL tickers — pooling happens
    here, by concatenation, not by combining per-ticker statistics.
    """
    n = len(net_bp)
    naive_t = None
    if n > 1:
        std = float(np.std(net_bp, ddof=1))
        if std > 0:
            naive_t = float(np.mean(net_bp)) / (std / np.sqrt(n))

    if n == 0:
        return BootstrapResult(0, 0, None, None, None, None, None, None, None, None)

    keys = block_key(timestamps, block=block)
    unique_blocks, block_index = np.unique(keys, return_inverse=True)
    n_blocks = len(unique_blocks)
    mean_net = float(np.mean(net_bp))

    if n_blocks < min_blocks:
        # Honest refusal: with a handful of calendar blocks the resampling distribution says
        # more about the blocks we happen to have than about the effect.
        return BootstrapResult(n, n_blocks, mean_net, None, None, None, None, None,
                               naive_t, None)

    # Group the trades by block once; resampling then means picking rows of this list.
    grouped = [net_bp[block_index == position] for position in range(n_blocks)]
    rng = np.random.default_rng(seed)
    means = np.empty(draws, dtype=float)
    for draw in range(draws):
        picked = rng.integers(0, n_blocks, size=n_blocks)
        # Concatenating preserves each block's own trade count, so a month that fired 400 times
        # carries the weight it actually had — resampling blocks, not trades.
        sample = np.concatenate([grouped[index] for index in picked])
        means[draw] = sample.mean()

    std_error = float(means.std(ddof=1))
    boot_t = mean_net / std_error if std_error > 0 else None
    # One-sided: the question is always "is this edge positive after costs".
    p_value = float((means <= 0).mean())
    low, high = (float(x) for x in np.percentile(means, [2.5, 97.5]))
    inflation = (abs(naive_t) / abs(boot_t)
                 if naive_t is not None and boot_t not in (None, 0.0) else None)

    return BootstrapResult(
        n_trades=n, n_blocks=n_blocks, mean_net_bp=mean_net, std_error_bp=std_error,
        t=boot_t, p_value=p_value, ci_low_bp=low, ci_high_bp=high,
        naive_t=naive_t, inflation_factor=inflation,
    )


def pool_trades(per_ticker: list[tuple[np.ndarray, pd.DatetimeIndex]]) -> tuple[np.ndarray, pd.DatetimeIndex]:
    """Concatenate per-ticker trade series into one pooled sample.

    Deliberately dumb: pooling is concatenation of the raw trades. Every attempt to be clever
    here (weighting, per-ticker statistics, variance combination) reintroduces an independence
    assumption through the back door.
    """
    returns = [r for r, _ in per_ticker if len(r)]
    stamps = [t for r, t in per_ticker if len(r)]
    if not returns:
        return np.empty(0, dtype=float), pd.DatetimeIndex([], tz="UTC")
    return np.concatenate(returns), pd.DatetimeIndex(np.concatenate([s.to_numpy() for s in stamps]), tz="UTC")
