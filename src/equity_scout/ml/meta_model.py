"""The meta-model: learns whether to follow the primary long signal, sized by P(follow).

Honest by construction. Primary signal = absolute momentum (the "side"). The model only ever decides
conviction. Validation is purged + embargoed walk-forward: each test block is scored by a model
trained only on earlier events whose label horizon cannot overlap the test block — so every reported
number is out-of-sample. The equity curve is built from OOS exposure, lagged one day (decide on t,
earn from t+1), so there is no look-ahead. Expectation is modest: with free daily data the realistic
goal is drawdown/risk reduction, not alpha. Periodic re-training (the "feedback loop") IS the
walk-forward: each fold retrains on newly available history.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

import numpy as np
import pandas as pd
from sklearn.base import ClassifierMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from equity_scout.market import PricePanel
from equity_scout.ml.features import FEATURE_NAMES, primary_long_signal, regime_features
from equity_scout.ml.fred import FRED_FEATURE_NAMES
from equity_scout.ml.labeling import triple_barrier_labels


@dataclass(frozen=True)
class MetaConfig:
    """One point in the search space the research loop explores ("many dimensions"). Defaults
    reproduce the original meta-model. The model only ever picks among regularised, shallow learners
    — depth is capped on purpose, the edge against overfitting is the validation, not model capacity."""

    features: tuple[str, ...] = field(default_factory=lambda: FEATURE_NAMES)
    model: str = "elastic_net"  # "elastic_net" | "random_forest"
    primary_lookback_months: int = 12
    horizon_days: int = 21
    barrier: float = 0.05  # symmetric profit-take = stop-loss

    def key(self) -> str:
        """Stable identity for the ledger (order-independent in features)."""
        feats = "+".join(sorted(self.features))
        return f"{feats}|{self.model}|{self.primary_lookback_months}|{self.horizon_days}|{self.barrier}"


DEFAULT_CONFIG = MetaConfig()


def _build_model(config: MetaConfig) -> ClassifierMixin:
    if config.model == "random_forest":  # shallow + leaf floor → low variance, hard to overfit
        return RandomForestClassifier(
            n_estimators=200, max_depth=3, min_samples_leaf=20, random_state=0
        )
    if config.model == "catboost":  # shallow gradient boosting; depth capped like the forest
        from catboost import CatBoostClassifier

        return CatBoostClassifier(
            iterations=200, depth=3, learning_rate=0.05, random_seed=0,
            verbose=False, allow_writing_files=False,
        )
    # elastic-net logistic: setting l1_ratio (sklearn >=1.8 API) selects the elastic-net penalty
    return LogisticRegression(solver="saga", l1_ratio=0.5, C=0.5, max_iter=5000)


@dataclass(frozen=True)
class BetRecord:
    """One out-of-sample decision, with the regime it was made in — the raw material for the
    self-analysis ("why was it wrong"). `correct` = the follow/avoid call matched the realised label."""

    date: str
    probability: float  # P(follow) the model assigned
    decision: str  # "follow" if probability > 0.5 else "avoid"
    label: int  # realised triple-barrier label (1 = profit hit first)
    correct: bool
    features: dict[str, float]  # regime feature values at the decision date


@dataclass(frozen=True)
class MetaResult:
    trained: bool
    equity: pd.Series  # OOS total-return index (1.0 at start)
    exposure: pd.Series  # daily target weight in the risk asset
    n_bets: int  # OOS bets the model scored
    oos_hit_rate: float  # share of OOS follow/avoid calls that were right (at p>0.5)
    avg_probability: float
    feature_importance: dict[str, float]
    bets: list[BetRecord] = field(default_factory=list)


def purged_walk_forward(
    event_dates: pd.DatetimeIndex,
    *,
    n_splits: int = 4,
    embargo_days: int = 21,
    horizon_days: int = 21,
    min_train: int = 24,
) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
    """Expanding-window walk-forward. For each test block, training is all earlier events whose
    label window (event + horizon + embargo) ends before the test block starts — purged + embargoed
    so a training label cannot peek into the test period."""
    n = len(event_dates)
    if n < min_train + n_splits:
        return
    fold = n // (n_splits + 1)
    if fold == 0:
        return
    for k in range(1, n_splits + 1):
        test_start = k * fold
        test_end = n if k == n_splits else (k + 1) * fold
        test = event_dates[test_start:test_end]
        cutoff = event_dates[test_start] - pd.Timedelta(days=horizon_days + embargo_days)
        train = event_dates[:test_start]
        train = train[train <= cutoff]
        if len(train) >= min_train and len(test) > 0:
            yield train, test


def _backtest_exposure(
    panel: PricePanel, exposure: pd.Series, risk: str, cash: str, costs_bps: float
) -> pd.Series:
    """Equity of a book that holds `exposure` in the risk asset, the rest in a cash proxy. Exposure
    is lagged one day (decide t, earn from t+1) → no look-ahead. Costs charged on exposure changes."""
    risk_ret = panel.closes[risk].pct_change().fillna(0.0)
    cash_ret = (
        panel.closes[cash].pct_change().fillna(0.0)
        if cash in panel.closes.columns
        else pd.Series(0.0, index=panel.dates)
    )
    held = exposure.reindex(panel.dates).ffill().fillna(0.0).shift(1).fillna(0.0)
    port_ret = held * risk_ret + (1.0 - held) * cash_ret
    cost = held.diff().abs().fillna(held) * (costs_bps / 10_000.0)
    return (1.0 + port_ret - cost).cumprod()


def _feature_weights(model: ClassifierMixin) -> np.ndarray:
    """Per-feature importance, whichever attribute the model exposes (logistic vs forest)."""
    if hasattr(model, "coef_"):
        return np.abs(model.coef_[0])
    return np.asarray(model.feature_importances_)


def run_meta_model(
    panel: PricePanel,
    config: MetaConfig = DEFAULT_CONFIG,
    *,
    risk: str = "SPY",
    cash: str = "BIL",
    costs_bps: float = 10.0,
    n_splits: int = 4,
    embargo_days: int = 21,
) -> MetaResult:
    feature_cols = list(config.features)
    primary = primary_long_signal(panel, risk, lookback_days=config.primary_lookback_months * 21)
    needs_fred = any(f in FRED_FEATURE_NAMES for f in feature_cols)
    features_all = regime_features(panel, risk, include_fred=needs_fred)
    feature_cols = [f for f in feature_cols if f in features_all.columns]  # robust if FRED unavailable
    features = features_all[feature_cols]
    rebalance = panel.rebalance_dates()
    bet_dates = pd.DatetimeIndex([d for d in rebalance if bool(primary.get(d, False))])
    labels = triple_barrier_labels(
        panel.closes[risk], bet_dates, horizon_days=config.horizon_days,
        profit_take=config.barrier, stop_loss=config.barrier,
    )
    usable = features.loc[features.index.intersection(labels.index)].dropna()
    X, y = usable, labels.loc[usable.index]

    oos_prob: dict[pd.Timestamp, float] = {}
    importances: list[np.ndarray] = []
    for train, test in purged_walk_forward(
        X.index, n_splits=n_splits, embargo_days=embargo_days, horizon_days=config.horizon_days
    ):
        x_train, y_train = X.loc[train], y.loc[train]
        x_test = X.loc[X.index.intersection(test)]
        if x_test.empty:
            continue
        if y_train.nunique() < 2:  # one class only → fall back to its base rate
            for date in x_test.index:
                oos_prob[date] = float(y_train.mean())
            continue
        scaler = StandardScaler().fit(x_train)
        model = _build_model(config)
        model.fit(scaler.transform(x_train), y_train)
        probs = model.predict_proba(scaler.transform(x_test))[:, 1]
        for date, prob in zip(x_test.index, probs):
            oos_prob[date] = float(prob)
        importances.append(_feature_weights(model))

    if not oos_prob:
        flat = pd.Series(1.0, index=panel.dates)
        return MetaResult(False, flat, pd.Series(0.0, index=panel.dates), 0, 0.0, 0.0, {})

    oos = pd.Series(oos_prob).sort_index()
    rebalance_exposure = pd.Series(0.0, index=rebalance)
    for date, prob in oos.items():
        rebalance_exposure.loc[date] = prob  # cash (0) on dates with no OOS bet
    daily_exposure = rebalance_exposure.reindex(panel.dates).ffill().fillna(0.0)
    equity = _backtest_exposure(panel, daily_exposure, risk, cash, costs_bps)

    y_oos = y.loc[oos.index]
    hit_rate = float(((oos > 0.5).astype(int) == y_oos).mean())
    importance = (
        dict(zip(feature_cols, np.mean(importances, axis=0) / (np.sum(np.mean(importances, axis=0)) or 1)))
        if importances
        else {}
    )
    bets = [
        BetRecord(
            date=date.date().isoformat(),
            probability=round(float(prob), 3),
            decision="follow" if prob > 0.5 else "avoid",
            label=int(y_oos.loc[date]),
            correct=bool((prob > 0.5) == bool(y_oos.loc[date])),
            features={k: round(float(X.loc[date, k]), 4) for k in feature_cols},
        )
        for date, prob in oos.items()
    ]
    return MetaResult(
        trained=True,
        equity=equity,
        exposure=daily_exposure,
        n_bets=len(oos),
        oos_hit_rate=hit_rate,
        avg_probability=float(oos.mean()),
        feature_importance={k: round(float(v), 3) for k, v in importance.items()},
        bets=bets,
    )
