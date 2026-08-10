"""Low-volatility anomaly (v16 T1): hold the CALMEST assets, weighted inversely to their risk.

A different family from everything else in this repo. Every existing strategy picks by
RETURN (momentum, trend) or by fixed allocation (60/40, Permanent). This one picks by RISK
alone and never looks at past performance — so its errors are uncorrelated with theirs, which
is the whole point of adding it rather than another momentum variant.

The anomaly: low-volatility assets have historically delivered equal or better risk-adjusted
returns than high-volatility ones, which plain CAPM says should not happen. Documented since
Haugen & Baker 1991, replicated across markets by Blitz & van Vliet 2007, and given a
mechanism by Frazzini & Pedersen 2014 ("Betting Against Beta": leverage-constrained investors
bid up risky assets, leaving the calm ones cheap). No promise attached — the effect has
weakened in US equities since ~2018 and is measured here, not assumed.

Two deliberate choices:
- **Inverse-vol weights, not equal weights.** Within the calm set, the calmer asset gets more.
  Equal-weighting would throw away the very signal the strategy selects on.
- **No absolute-momentum crash switch.** GEM, DAA and the sector rotation all have one, and
  bolting a third momentum filter onto a risk-selected book would quietly turn it into another
  momentum strategy. This one stays a pure risk-selector; the depot's protection chain
  (`autotrader_protections`) is where drawdown control belongs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView

# 63 trading days ~ one quarter: long enough that a single turbulent week does not decide the
# ranking, short enough to react within a regime. The vol_target strategy uses 21 for the same
# reason in reverse (it WANTS to react fast to scale exposure).
VOL_WINDOW_DAYS = 63
# A vol below this is a data artefact, not a calm asset (a stale price series repeats its last
# value and reads as zero risk). Ranking such a ticker first would put the whole book into a
# broken feed — the single most damaging failure mode this strategy has.
MIN_PLAUSIBLE_VOL = 0.005


class LowVolatilityStrategy:
    name = "Low-Vol-Anomalie"

    def __init__(
        self,
        universe: tuple[str, ...] = tuple(ETF_TICKERS),
        top_n: int = 5,
        safe: str = "BIL",
        vol_window_days: int = VOL_WINDOW_DAYS,
        min_rankable: int = 6,
    ) -> None:
        self.universe = universe
        self.top_n = top_n
        self.safe = safe
        self.vol_window_days = vol_window_days
        self.min_rankable = min_rankable

    def _vols(self, market: MarketView) -> dict[str, float]:
        out: dict[str, float] = {}
        for ticker in self.universe:
            vol = market.realised_vol(ticker, window_days=self.vol_window_days)
            # Both guards matter: None is "no history yet", <= MIN is "the feed is stale".
            if vol is not None and vol >= MIN_PLAUSIBLE_VOL:
                out[ticker] = vol
        return out

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        vols = self._vols(market)
        if len(vols) < self.min_rankable:
            # Too little to rank: cash proxy, never a guessed ranking. Same stance as the
            # other strategies' defensive fallback.
            return [TargetWeight(self.safe, 1.0)] if market.last_price(self.safe) else []
        calmest = sorted(vols, key=lambda t: vols[t])[: self.top_n]
        inverse = {t: 1.0 / vols[t] for t in calmest}
        total = sum(inverse.values())
        return [TargetWeight(t, inverse[t] / total) for t in calmest]
