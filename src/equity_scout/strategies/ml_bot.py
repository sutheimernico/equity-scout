"""ML trading bots: the entry-model champions actually trade — forward, on paper.

Before v6 the ML entry score was logged and resolved but never traded anywhere (review finding
2026-07-13). These two strategies close that loop through the existing seams: each implements the
state-free `Strategy` protocol, so the same `decide` runs in backtest and forward paper with zero
new account machinery.

- `MLLongStrategy` scores its universe with the LONG champion (`family="entry"`,
  P(beats SPY over the horizon)) and holds the top K scores above the threshold, equal-weight.
- `MLShortStrategy` scores with the SHORT champion (`family="entry_short"`, P(lags SPY)) and
  SHORTS the top K, at half gross exposure by default. Its universe is a hardcoded liquid
  large-cap whitelist — free data has no borrow-availability or market-cap feed, so "shortable"
  is a LABELLED SIMPLIFICATION, not a real locate.

Honesty invariants: a bot with no promoted champion returns NO positions (it never trades an
undemonstrated edge — the registry gate is the single promotion authority); features come from
`MarketView.history` (strictly pre-as_of, look-ahead-safe); scores are calibrated probabilities,
never price forecasts. Decisions recompute each advance — score churn is bounded by the threshold
+ top-K selection and every rebalance pays the normal turnover cost.
"""
from __future__ import annotations

import pandas as pd

from equity_scout.market import MarketView
from equity_scout.ml.entry_features import MIN_HISTORY, build_feature_row, market_context
from equity_scout.ml.entry_model import EntryModel
from equity_scout.ml.model_registry import entry_champion
from equity_scout.strategies.base import TargetWeight

# Liquid US mega/large caps the short bot may trade. A curated stand-in for a real
# borrow-availability + market-cap screen (neither exists on free data) — labelled simplification.
SHORTABLE_TICKERS: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V",
    "UNH", "XOM", "JNJ", "WMT", "PG", "MA", "HD", "COST", "ORCL", "KO",
    "PEP", "BAC", "CRM", "CSCO", "ABBV", "CVX", "MRK", "ADBE", "NFLX", "AMD",
    "INTC", "DIS",
)

DEFAULT_TOP_K = 5
DEFAULT_THRESHOLD = 60  # minimum 0-100 champion score to act on
DEFAULT_SHORT_EXPOSURE = 0.5  # half gross for the short book — unbounded-loss side stays smaller


def score_universe(
    model: EntryModel, market: MarketView, tickers: list[str], *, benchmark: str = "SPY"
) -> dict[str, int]:
    """Champion scores (0-100) per ticker from the visible market only. Tickers with too little
    history or an incomplete feature row are silently absent — a missing score is an honest
    non-opinion, never a fabricated neutral 50."""
    panel = market.visible_panel()
    if benchmark not in panel.tickers:
        return {}
    context_df = market_context(panel, benchmark=benchmark)
    context_df = context_df.dropna()
    if context_df.empty:
        return {}
    context = context_df.iloc[-1].to_dict()
    scores: dict[str, int] = {}
    for ticker in dict.fromkeys(tickers):
        if ticker == benchmark:
            continue
        hist = market.history(ticker)
        if len(hist) < MIN_HISTORY:
            continue
        as_of = pd.Timestamp(hist.index[-1])
        features = build_feature_row(hist, context, as_of)
        if features is None:
            continue
        scores[ticker] = model.score_row(features)
    return scores


def _top_picks(scores: dict[str, int], *, top_k: int, threshold: int) -> list[str]:
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))  # score desc, ticker asc
    return [ticker for ticker, score in ranked if score >= threshold][:top_k]


class MLLongStrategy:
    """Long bot: hold the top-K highest LONG-champion scores above the threshold, equal-weight."""

    name = "ML Long Bot"

    def __init__(
        self,
        *,
        model: EntryModel | None,
        tickers: list[str],
        benchmark: str = "SPY",
        top_k: int = DEFAULT_TOP_K,
        threshold: int = DEFAULT_THRESHOLD,
        exposure: float = 1.0,
    ) -> None:
        self._model = model
        self._tickers = list(tickers)
        self._benchmark = benchmark
        self._top_k = top_k
        self._threshold = threshold
        self._exposure = exposure

    @classmethod
    def from_registry(cls, db_path: str, *, tickers: list[str], **kwargs) -> MLLongStrategy:
        champ = entry_champion(db_path, family="entry")
        return cls(model=champ[1] if champ else None, tickers=tickers, **kwargs)

    @property
    def ready(self) -> bool:
        """False without a promoted champion — the caller should skip (and say so), not trade."""
        return self._model is not None

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        if self._model is None:
            return []  # no demonstrated edge → no positions, never a fallback heuristic
        scores = score_universe(self._model, market, self._tickers, benchmark=self._benchmark)
        picks = _top_picks(scores, top_k=self._top_k, threshold=self._threshold)
        if not picks:
            return []
        weight = self._exposure / len(picks)
        return [TargetWeight(ticker, weight) for ticker in picks]


class MLShortStrategy:
    """Short bot: SHORT the top-K highest SHORT-champion scores (P(lags SPY)) above the
    threshold, equal-weight at reduced gross exposure, whitelist-only."""

    name = "ML Short Bot"

    def __init__(
        self,
        *,
        model: EntryModel | None,
        tickers: list[str] | None = None,
        benchmark: str = "SPY",
        top_k: int = DEFAULT_TOP_K,
        threshold: int = DEFAULT_THRESHOLD,
        exposure: float = DEFAULT_SHORT_EXPOSURE,
    ) -> None:
        self._model = model
        self._tickers = list(tickers) if tickers is not None else list(SHORTABLE_TICKERS)
        self._benchmark = benchmark
        self._top_k = top_k
        self._threshold = threshold
        self._exposure = exposure

    @classmethod
    def from_registry(cls, db_path: str, **kwargs) -> MLShortStrategy:
        champ = entry_champion(db_path, family="entry_short")
        return cls(model=champ[1] if champ else None, **kwargs)

    @property
    def ready(self) -> bool:
        return self._model is not None

    def decide(self, as_of: pd.Timestamp, market: MarketView) -> list[TargetWeight]:
        if self._model is None:
            return []
        scores = score_universe(self._model, market, self._tickers, benchmark=self._benchmark)
        picks = _top_picks(scores, top_k=self._top_k, threshold=self._threshold)
        if not picks:
            return []
        weight = self._exposure / len(picks)
        return [TargetWeight(ticker, weight, side="short") for ticker in picks]
