"""Trader #3: the matrix strategy — the first thing in this repo that trades a matrix finding.

Until now `find_plateaus` produced regions that nothing read (see matrix/registry.py). This class
closes that gap: it reads the register of QUALIFIED plateaus and turns the ones firing today into
target weights.

## What it does and does not decide

It decides nothing about which rules are good — that judgement lives entirely in the register and
its four gates (plateau, bootstrap, robustness, hold-out). This class is deliberately dumb: for
each qualified plateau, check whether its signal fires right now for each ticker, and size the
position from the plateau's own measured uncertainty.

That split matters. A strategy that re-evaluated the evidence at trade time would be a second,
unregistered search — and searching twice is how this project already lost five weeks once.

## Sizing: down for uncertainty, never up

`QualifiedPlateau.risk_weight` maps the bootstrap t onto [0, 1] (t = 8 → full, t = 2 → quarter).
Total exposure is additionally capped at MAX_GROSS_EXPOSURE, so no combination of plateaus can
produce leverage: the account permits 4x, this strategy never asks for more than 1x. Nico's
"entsprechende Hebel" is honoured as *relative* sizing between findings, which is the only part
of it that a paper track record can justify today.

## Short

Plateaus carry a `side`. A region whose forward returns are consistently NEGATIVE after costs is
a short finding, and `TargetWeight(side="short")` already exists in the strategy seam — so a
qualified short plateau shorts, with the same gates as a long one. Whether the borrow exists is
the executing lane's problem, not the strategy's: measured on 2026-08-19, none of the 50 largest
daily losers were shortable (warrants and micro caps), while liquid names like MRNA were.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from equity_scout.matrix.registry import (
    DEFAULT_MATRIX_DB_PATH,
    QualifiedPlateau,
    load_qualified,
)
from equity_scout.strategies.base import TargetWeight

if TYPE_CHECKING:
    import pandas as pd

    from equity_scout.market import MarketView

# One plateau may never own the book: even a fully qualified finding is one rule among many, and
# the register is young. 25 % is the same order as the ETF sleeves' concentration cap.
MAX_WEIGHT_PER_PLATEAU = 0.25
MAX_WEIGHT_PER_TICKER = 0.10
MAX_GROSS_EXPOSURE = 1.0  # no leverage, ever — the protection chain assumes this
MAX_TICKERS_PER_PLATEAU = 10


class MatrixStrategy:
    """Trades every qualified plateau whose signal fires today.

    `signal_fires` is injected rather than imported so the strategy stays testable without the
    matrix's data layer, and so the signal implementations remain the single source of truth in
    `matrix/signals.py` instead of being restated here.
    """

    def __init__(
        self,
        *,
        db_path: str = DEFAULT_MATRIX_DB_PATH,
        universe: list[str] | None = None,
        signal_fires=None,
        name: str = "Matrix (qualifizierte Plateaus)",
    ) -> None:
        self.name = name
        self._db_path = db_path
        self._universe = universe
        self._signal_fires = signal_fires

    @property
    def ready(self) -> bool:
        """False while no plateau has passed all four gates.

        The autotrader consults this the same way it consults the ML bots' `.ready`: an
        unqualified strategy contributes NOTHING rather than a neutral guess, because a neutral
        guess still consumes a sleeve slot and dilutes the ones that earned it.
        """
        return bool(load_qualified(self._db_path))

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        plateaus = load_qualified(self._db_path)
        if not plateaus or self._signal_fires is None:
            # Empty is the honest answer: no qualified finding means no position. The remainder
            # is held as cash by the engine.
            return []

        universe = self._universe or list(getattr(market, "tickers", []) or [])
        if not universe:
            return []

        raw: dict[tuple[str, str], float] = {}
        for plateau in plateaus:
            weight_each = self._plateau_weight(plateau)
            if weight_each <= 0:
                continue
            firing = [
                ticker for ticker in universe
                if self._signal_fires(plateau, ticker, as_of, market)
            ][:MAX_TICKERS_PER_PLATEAU]
            if not firing:
                continue
            per_ticker = min(weight_each / len(firing), MAX_WEIGHT_PER_TICKER)
            for ticker in firing:
                key = (ticker, plateau.side)
                raw[key] = raw.get(key, 0.0) + per_ticker

        return self._capped(raw)

    def _plateau_weight(self, plateau: QualifiedPlateau) -> float:
        return min(MAX_WEIGHT_PER_PLATEAU, MAX_WEIGHT_PER_PLATEAU * plateau.risk_weight)

    @staticmethod
    def _capped(raw: dict[tuple[str, str], float]) -> list[TargetWeight]:
        """Enforce the per-ticker and gross caps, scaling down proportionally.

        Scaling rather than truncating keeps the RELATIVE conviction between findings intact,
        which is the only thing the sizing was supposed to express in the first place.
        """
        if not raw:
            return []
        capped = {key: min(weight, MAX_WEIGHT_PER_TICKER) for key, weight in raw.items()}
        gross = sum(capped.values())
        if gross > MAX_GROSS_EXPOSURE:
            factor = MAX_GROSS_EXPOSURE / gross
            capped = {key: weight * factor for key, weight in capped.items()}
        return [
            TargetWeight(ticker=ticker, weight=round(weight, 6), side=side)
            for (ticker, side), weight in sorted(capped.items())
            if weight > 0.0005  # dust: a 5 bp position cannot pay its own commission
        ]
