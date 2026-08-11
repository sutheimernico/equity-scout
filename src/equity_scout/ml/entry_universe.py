"""The entry model's TRAINING universe — fixed and ex ante, not the current watchlist.

Why this module exists (found 2026-08-11, see
`docs/research/2026-08-11-champion-was-a-measurement-artifact.md`): the trainer resolved its
universe from `load_latest_watchlist`, i.e. from whatever the screener had picked that morning.
Three problems came with that, and the third is the one that broke the champion arena:

1. **Endogenous.** The watchlist is the output of a screen on TODAY's data, while training runs
   from 2007. Nobody held those 30 names in 2010.
2. **Small and gappy.** 19 of 30 names survived the history filter, because international listings
   (`BBSE3.SA`, `INSW`, `LPG`, `SNDK`) would have cut the panel's span too far.
3. **It changed almost every night** — and so did the sample. `n_train` swung between 80 and 4806
   in the `entry` family. AUCs measured on different samples are not comparable, yet the promotion
   gate compared them to three decimals against a 0.01 bar.

An index-constituent snapshot fixes all three: it is picked by size and liquidity rather than by
the return-driven features the model trains on, it is immutable once stored, and it is an order of
magnitude larger.

**Honest limit — this reduces bias, it does not remove it.** The snapshot holds the index members
as of ITS date, so names that dropped out of the index (or delisted) earlier are missing. That is
survivorship bias, and free yfinance data cannot fix it: a delisted ticker returns no history. The
decisive difference is that the remaining bias is not a RETURN screen and no longer varies from
night to night.
"""
from __future__ import annotations

from equity_scout.models import Instrument

# The snapshot the entry model trains on. Pinned deliberately: a "latest snapshot" lookup would
# reintroduce exactly the drift this module removes. 2026-07-02 is the curated index universe
# (S&P 500 + STOXX 600 + Nikkei 225 + the hand-curated global list); the later snapshots are the
# "screen everything" universe (6592/7499 names), whose long tail is mostly illiquid listings with
# too little history to train on.
TRAINING_UNIVERSE_AS_OF = "2026-07-02"

# US only. The benchmark is SPY and the market-context features (breadth, VIX regime, drawdown) are
# US-derived, so a Tokyo or São Paulo listing is scored against a market it does not trade in — the
# v15 P3 round already found non-US names encoding a regime gap rather than a signal. 503 US names
# in the pinned snapshot is more sample than the model has ever had.
TRAINING_REGION = "US"


def training_universe(
    instruments: list[Instrument], *, region: str | None = TRAINING_REGION
) -> list[str]:
    """Tickers of the fixed training universe, sorted and deduped.

    Sorted alphabetically so the list is byte-identical across runs — the point of the whole module
    is that two nights train on the SAME universe. `region=None` takes every instrument (for a
    caller that deliberately wants the global set).

    The order is arbitrary with respect to returns, which is what matters: any cap a caller applies
    on top of it cannot select for the outcome being predicted.
    """
    return sorted({i.ticker for i in instruments if region is None or i.region == region})
