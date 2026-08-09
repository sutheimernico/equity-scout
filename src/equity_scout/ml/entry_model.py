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
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from equity_scout.ml.entry_eval import HORIZON_DAYS, classification_scores, rank_ic
from equity_scout.ml.meta_model import _feature_weights, purged_walk_forward

# Every preset run_train_entry trains per night; the hardened registry gate alone decides
# which one (if any) becomes champion (plan v6 P2).
ENTRY_PRESETS = ("random_forest", "elastic_net", "catboost", "ensemble")


def _build_estimator(model: str) -> ClassifierMixin:
    """Small fixed model set — shallow depth + a leaf floor / strong L1-L2 penalty keep variance
    low, so the edge (if any) comes from the walk-forward validation, not model capacity."""
    if model == "random_forest":
        return RandomForestClassifier(
            n_estimators=200, max_depth=3, min_samples_leaf=20, random_state=0
        )
    if model == "elastic_net":
        return LogisticRegression(solver="saga", l1_ratio=0.5, C=0.5, max_iter=5000)
    if model == "catboost":
        from catboost import CatBoostClassifier  # heavy import stays lazy

        # Same capped capacity philosophy as the meta-model's catboost preset.
        return CatBoostClassifier(
            iterations=300, depth=3, learning_rate=0.1,
            verbose=False, allow_writing_files=False, random_seed=0,
        )
    if model == "ensemble":
        return VotingClassifier(
            estimators=[
                ("elastic_net", _build_estimator("elastic_net")),
                ("random_forest", _build_estimator("random_forest")),
            ],
            voting="soft",
        )
    raise ValueError(f"unknown model kind: {model!r} (expected one of {ENTRY_PRESETS})")


@dataclass(frozen=True)
class EntryModel:
    """A fitted entry-quality model. Holds the scaler, the estimator, and the exact feature order
    they were fitted on, so scoring re-orders any input to the training layout before predicting.

    `calibrator` (optional, fitted on OUT-OF-SAMPLE walk-forward probabilities only — never
    in-sample) maps raw estimator probabilities to calibrated ones at scoring time."""

    scaler: StandardScaler
    estimator: ClassifierMixin
    feature_columns: tuple[str, ...]
    model_kind: str
    calibrator: object | None = None

    def _proba(self, X: pd.DataFrame) -> np.ndarray:
        ordered = X[list(self.feature_columns)]
        raw = self.estimator.predict_proba(self.scaler.transform(ordered))[:, 1]
        # getattr: artifacts pickled before the calibrator field existed unpickle without it.
        calibrator = getattr(self, "calibrator", None)
        if calibrator is None:
            return raw
        return np.clip(np.asarray(calibrator.predict(raw), dtype=float), 0.0, 1.0)

    def score_many(self, X: pd.DataFrame) -> np.ndarray:
        """Integer 0-100 score per row = round(P(beats benchmark) * 100). This is THE one place
        the probability becomes a score, so the surface is consistent everywhere."""
        return np.rint(self._proba(X) * 100.0).astype(int)

    def score_row(self, features: dict) -> int:
        """Score a single feature dict. Every column the model was FITTED on must be present:
        `pd.DataFrame([features], columns=...)` would otherwise fill a missing one with NaN and
        score it silently. Since v15 P3 the registry holds models with different feature sets
        (evidence-featured challengers next to price-only ones), so handing the wrong block to
        the wrong model must fail loudly. Extra keys are ignored, exactly as before."""
        missing = [column for column in self.feature_columns if column not in features]
        if missing:
            raise ValueError(
                f"feature row is missing {len(missing)} column(s) the model was fitted on: "
                f"{missing}"
            )
        row = pd.DataFrame([features], columns=list(self.feature_columns))
        return int(self.score_many(row)[0])


def train_entry_model(
    X: pd.DataFrame, y: pd.Series, *, model: str = "random_forest", calibrator: object | None = None
) -> EntryModel:
    """Fit the scaler + estimator on the FULL dataset (the deployed artifact). Every performance
    number must come from `walk_forward_evaluate` instead — this fit is in-sample by construction.
    `calibrator` must have been fitted on OOS probabilities by the caller (run_train_entry)."""
    feature_columns = tuple(X.columns)
    scaler = StandardScaler().fit(X)
    estimator = _build_estimator(model)
    estimator.fit(scaler.transform(X), y)
    return EntryModel(scaler, estimator, feature_columns, model, calibrator)


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


def walk_forward_efficiency(oos_auc: float | None, is_auc: float | None) -> float | None:
    """Share of the in-sample edge that survives out-of-sample (v13 Q3), on EXCESS AUC over
    the 0.5 coin-flip base: (oos - 0.5) / (is - 0.5). A raw AUC ratio could hardly fall
    below 0.5 (0.5/1.0 is its floor), which would make the overfit label unreachable.
    None when either side is missing or there is no in-sample edge to preserve
    (is_auc <= 0.5). SOFT diagnostic only — no gate reads it; WFE < 0.5 = likely
    overfit (heuristic)."""
    if oos_auc is None or is_auc is None or is_auc <= 0.5:
        return None
    return round((oos_auc - 0.5) / (is_auc - 0.5), 4)


def walk_forward_evaluate(
    X: pd.DataFrame,
    y: pd.Series,
    meta: pd.DataFrame,
    *,
    model: str = "random_forest",
    n_splits: int = 4,
    horizon_days: int = HORIZON_DAYS,
    trading_days: pd.DatetimeIndex | None = None,
    collect_oos: bool = False,
) -> dict:
    """Group-aware purged walk-forward (see `_date_grouped_folds`): the split is on unique `as_of`
    dates, so all rows of a date share a fold side. `trading_days` (e.g. `panel.dates`) enables the
    exact trading-day purge in `purged_walk_forward`; omitting it falls back to its conservative
    calendar-day bound. Returns OOS {auc, brier, rank_ic, n_oos, n_splits_used, feature_importance}.
    `collect_oos=True` additionally returns the raw OOS arrays under "oos" ({"prob", "y"}) so the
    caller can fit a calibrator on OUT-OF-SAMPLE probabilities — strip that key before persisting
    metrics (numpy arrays are not JSON).
    """
    X = X.reset_index(drop=True)
    y = y.reset_index(drop=True)
    as_of = pd.to_datetime(meta["as_of"]).reset_index(drop=True)
    realized = pd.to_numeric(meta["relative_return"]).reset_index(drop=True)

    oos_prob: dict[int, float] = {}
    importances: list[np.ndarray] = []
    is_aucs: list[float] = []  # per real fit, for the walk-forward efficiency (v13 Q3)
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
        train_probs = estimator.predict_proba(scaler.transform(x_train))[:, 1]
        is_auc_split = classification_scores(y_train.to_numpy(), train_probs)["auc"]
        if is_auc_split is not None:
            is_aucs.append(is_auc_split)
        try:
            importances.append(_feature_weights(estimator))
        except AttributeError:
            pass  # the voting ensemble exposes neither coef_ nor feature_importances_

    if not oos_prob:
        empty = {
            "auc": None, "brier": None, "rank_ic": None,
            "n_oos": 0, "n_splits_used": 0, "feature_importance": {},
            "is_auc": None, "wfe": None,
        }
        if collect_oos:
            empty["oos"] = {"prob": np.array([]), "y": np.array([])}
        return empty

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

    is_auc = round(float(np.mean(is_aucs)), 4) if is_aucs else None
    result = {
        "auc": scores["auc"],
        "brier": scores["brier"],
        "rank_ic": ic,
        "n_oos": len(positions),
        "n_splits_used": n_splits_used,
        "feature_importance": importance,
        "is_auc": is_auc,
        "wfe": walk_forward_efficiency(scores["auc"], is_auc),
    }
    if collect_oos:
        result["oos"] = {"prob": prob_oos, "y": y_oos}
    return result
