"""Naive risk parity (v16 T4): every asset class contributes the same risk, nobody forecasts.

The fourth family, and the only one in this repo that makes NO selection at all. 60/40 fixes
weights by capital; momentum and low-vol select a subset; this one holds everything and sizes
each position so its risk contribution is equal — a bond position becomes large precisely
because bonds are calm, an equity position small because equities are not.

Why that is a distinct idea and not a variant of `LowVolatilityStrategy`: low-vol EXCLUDES the
turbulent assets, risk parity KEEPS them and shrinks them. The first is a bet that calm assets
are mispriced; the second is a refusal to bet at all, on the grounds that a 60/40 book is in
practice ~90 % equity risk and that concentration is unintentional rather than chosen.

"Naive" is the honest qualifier: true risk parity equalises risk CONTRIBUTIONS using the full
covariance matrix, which needs a stable correlation estimate. Inverse-volatility weighting
equalises stand-alone risks and equals true risk parity only when correlations are uniform.
The simplification is deliberate — an unstable 21x21 covariance estimate on 8 years of ETF
history would add estimation error, not precision (Qian 2005; Asness/Frazzini/Pedersen 2012
on the leverage-free variant of the same argument).

Deliberately NO leverage: the classic risk-parity result depends on levering the bond leg, and
the `TargetWeight` contract caps magnitudes at 1.0 with weights summing to at most 1. This book
is therefore the unlevered version, which historically means lower return AND lower drawdown
than the levered original. Stated so nobody reads its flat equity curve as a failure of the
idea rather than of the leverage constraint.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView

# One asset per class, not the whole ETF universe: risk parity over 21 tickers that include
# eleven US sector ETFs would equalise risk across eleven slices of the SAME risk factor and
# call the result diversification.
DEFAULT_SLEEVE: tuple[str, ...] = (
    "SPY",   # US equity
    "VEU",   # non-US equity
    "IEF",   # intermediate treasuries
    "TLT",   # long treasuries
    "GLD",   # gold
    "DBC",   # broad commodities
    "VNQ",   # real estate
)
VOL_WINDOW_DAYS = 63
MIN_PLAUSIBLE_VOL = 0.005
# Even a very calm asset must not become the entire book. Without a cap, one asset in a quiet
# regime (short treasuries in 2021) takes 70 %+ and the "parity" claim stops being true.
MAX_WEIGHT_PER_ASSET = 0.40


class RiskParityStrategy:
    name = "Risk Parity (naiv)"

    def __init__(
        self,
        sleeve: tuple[str, ...] = DEFAULT_SLEEVE,
        safe: str = "BIL",
        vol_window_days: int = VOL_WINDOW_DAYS,
        min_assets: int = 4,
        max_weight: float = MAX_WEIGHT_PER_ASSET,
    ) -> None:
        self.sleeve = sleeve
        self.safe = safe
        self.vol_window_days = vol_window_days
        self.min_assets = min_assets
        self.max_weight = max_weight

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        vols: dict[str, float] = {}
        for ticker in self.sleeve:
            vol = market.realised_vol(ticker, window_days=self.vol_window_days)
            if vol is not None and vol >= MIN_PLAUSIBLE_VOL:
                vols[ticker] = vol
        if len(vols) < self.min_assets:
            return [TargetWeight(self.safe, 1.0)] if market.last_price(self.safe) else []

        inverse = {t: 1.0 / v for t, v in vols.items()}
        total = sum(inverse.values())
        raw = {t: inverse[t] / total for t in inverse}
        # Cap, then renormalise the uncapped remainder so the book still invests fully. Any
        # weight the cap frees goes to the OTHER assets by their own risk share, not to cash —
        # cash would be a market call, and this strategy makes none.
        capped = {t: min(w, self.max_weight) for t, w in raw.items()}
        spare = 1.0 - sum(capped.values())
        if spare > 1e-9:
            headroom = {t: self.max_weight - w for t, w in capped.items()
                        if self.max_weight - w > 1e-9}
            room_total = sum(headroom.values())
            if room_total > 1e-9:
                for t, room in headroom.items():
                    capped[t] += spare * (room / room_total)
        return [TargetWeight(t, round(w, 10)) for t, w in sorted(capped.items())]
