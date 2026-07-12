"""The entry-quality model: scores a watchlist entry 0-100 = P(it beats SPY over the horizon).

Wraps a fitted `StandardScaler` + a shallow, regularised sklearn classifier (the same low-variance
learners the meta-model uses) behind a stable feature order. The 0-100 score is `round(P*100)` in
exactly one place — it is a calibrated probability, never a price forecast or advice (spec §5.2,
honesty invariant #4).

Every reported number comes from `walk_forward_evaluate`, which reuses `meta_model.purged_walk_forward`
for OUT-OF-SAMPLE validation (honesty invariant #2). The split is GROUP-AWARE on unique `as_of`
DATES: all rows sharing a date go to the same side of a split, because they share the same forward
horizon window — letting some rows of a date train while their same-date siblings test would leak
overlapping look-ahead exposure across the fold boundary and inflate the score. A fold whose train
side collapses to one class falls back to that class's base rate (mirroring the meta-model), so a
degenerate fold reports its honest prior instead of crashing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pandas as pd
from sklearn.base import ClassifierMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from equity_scout.ml.entry_eval import HORIZON_DAYS, classification_scores, rank_ic
from equity_scout.ml.meta_model import _feature_weights, purged_walk_forward


def _build_estimator(model: str) -> ClassifierMixin:
    """Small fixed model set — shallow depth + a leaf floor / strong L1-L2 penalty keep variance
    low, so the edge (if any) comes from the walk-forward validation, not model capacity."""
    if model == "random_forest":
        return RandomForestClassifier(
            n_estimators=200, max_depth=3, min_samples_leaf=20, random_state=0
        )
    if model == "elastic_net":
        return LogisticRegression(solver="saga", l1_ratio=0.5, C=0.5, max_iter=5000)
    raise ValueError(f"unknown model kind: {model!r} (expected 'random_forest' or 'elastic_net')")


@dataclass(frozen=True)
class EntryModel:
    """A fitted entry-quality model. Holds the scaler, the estimator, and the exact feature order
    they were fitted on, so scoring re-orders any input to the training layout before predicting."""

    scaler: StandardScaler
    estimator: ClassifierMixin
    feature_columns: tuple[str, ...]
    model_kind: str

    def _proba(self, X: pd.DataFrame) -> np.ndarray:
        ordered = X[list(self.feature_columns)]
        return self.estimator.predict_proba(self.scaler.transform(ordered))[:, 1]

    def score_many(self, X: pd.DataFrame) -> np.ndarray:
        """Integer 0-100 score per row = round(P(beats benchmark) * 100). This is THE one place
        the probability becomes a score, so the surface is consistent everywhere."""
        return np.rint(self._proba(X) * 100.0).astype(int)

    def score_row(self, features: dict) -> int:
        """Score a single feature dict (keys must cover `feature_columns`)."""
        row = pd.DataFrame([features], columns=list(self.feature_columns))
        return int(self.score_many(row)[0])


def train_entry_model(
    X: pd.DataFrame, y: pd.Series, *, model: str = "random_forest"
) -> EntryModel:
    """Fit the scaler + estimator on the FULL dataset (the deployed artifact). Every performance
    number must come from `walk_forward_evaluate` instead — this fit is in-sample by construction."""
    feature_columns = tuple(X.columns)
    scaler = StandardScaler().fit(X)
    estimator = _build_estimator(model)
    estimator.fit(scaler.transform(X), y)
    return EntryModel(scaler, estimator, feature_columns, model)


def _date_grouped_folds(
    as_of: pd.Series,
    *,
    n_splits: int,
    horizon_days: int,
    trading_days: pd.DatetimeIndex | None = None,
) -> Iterator[tuple[pd.Series, pd.Series]]:
    """Yield (train_mask, test_mask) boolean Series per walk-forward fold. THE split mechanism:
    `purged_walk_forward` runs on the sorted unique `as_of` DATES, and each mask selects ALL rows
    sharing a date. So no date can straddle a split — rows on one date share the same forward
    horizon window, hence the same look-ahead exposure, and must never sit on opposite fold sides.
    `trading_days` (the full daily calendar `as_of` was sampled from, e.g. `panel.dates`) lets the
    purge use exact trading-day positions instead of a calendar-day approximation — see
    `purged_walk_forward`."""
    date_index = pd.DatetimeIndex(sorted(as_of.unique()))
    for train_dates, test_dates in purged_walk_forward(
        date_index, n_splits=n_splits, horizon_days=horizon_days, trading_days=trading_days
    ):
        yield as_of.isin(train_dates), as_of.isin(test_dates)


def walk_forward_evaluate(
    X: pd.DataFrame,
    y: pd.Series,
    meta: pd.DataFrame,
    *,
    model: str = "random_forest",
    n_splits: int = 4,
    horizon_days: int = HORIZON_DAYS,
    trading_days: pd.DatetimeIndex | None = None,
) -> dict:
    """Group-aware purged walk-forward (see `_date_grouped_folds`): the split is on unique `as_of`
    dates, so all rows of a date share a fold side. `trading_days` (e.g. `panel.dates`) enables the
    exact trading-day purge in `purged_walk_forward`; omitting it falls back to its conservative
    calendar-day bound. Returns OOS {auc, brier, rank_ic, n_oos, n_splits_used, feature_importance}.
    """
    X = X.reset_index(drop=True)
    y = y.reset_index(drop=True)
    as_of = pd.to_datetime(meta["as_of"]).reset_index(drop=True)
    realized = pd.to_numeric(meta["relative_return"]).reset_index(drop=True)

    oos_prob: dict[int, float] = {}
    importances: list[np.ndarray] = []
    n_splits_used = 0
    for train_mask, test_mask in _date_grouped_folds(
        as_of, n_splits=n_splits, horizon_days=horizon_days, trading_days=trading_days
    ):
        x_train = X[train_mask]
        y_train = y[train_mask]
        x_test = X[test_mask]
        if x_train.empty or x_test.empty:
            continue
        n_splits_used += 1
        if y_train.nunique() < 2:  # one class only → honest base-rate fallback (see meta_model)
            base = float(y_train.mean())
            for pos in x_test.index:
                oos_prob[pos] = base
            continue
        scaler = StandardScaler().fit(x_train)
        estimator = _build_estimator(model)
        estimator.fit(scaler.transform(x_train), y_train)
        probs = estimator.predict_proba(scaler.transform(x_test))[:, 1]
        for pos, prob in zip(x_test.index, probs):
            oos_prob[pos] = float(prob)
        importances.append(_feature_weights(estimator))

    if not oos_prob:
        return {
            "auc": None, "brier": None, "rank_ic": None,
            "n_oos": 0, "n_splits_used": 0, "feature_importance": {},
        }

    positions = sorted(oos_prob)
    y_oos = y.loc[positions].to_numpy()
    prob_oos = np.array([oos_prob[p] for p in positions])
    scores = classification_scores(y_oos, prob_oos)
    ic = rank_ic(prob_oos, realized.loc[positions].to_numpy())

    importance: dict[str, float] = {}
    if importances:
        mean_imp = np.mean(importances, axis=0)
        total = float(np.sum(mean_imp)) or 1.0
        importance = {c: round(float(v / total), 4) for c, v in zip(X.columns, mean_imp)}

    return {
        "auc": scores["auc"],
        "brier": scores["brier"],
        "rank_ic": ic,
        "n_oos": len(positions),
        "n_splits_used": n_splits_used,
        "feature_importance": importance,
    }
