"""CatBoost as a third meta-model learner — builds with the capped depth and trains end-to-end."""
from __future__ import annotations

from equity_scout.market import PricePanel
from equity_scout.ml.meta_model import MetaConfig, _build_model, run_meta_model


def test_build_model_returns_shallow_catboost() -> None:
    model = _build_model(MetaConfig(model="catboost"))
    assert model.__class__.__name__ == "CatBoostClassifier"
    assert model.get_param("depth") == 3  # capacity stays capped, like the forest


def test_meta_model_trains_with_catboost(wavy_panel: PricePanel) -> None:
    result = run_meta_model(wavy_panel, MetaConfig(model="catboost"))
    assert result.trained
    assert result.n_bets > 0
    assert set(result.feature_importance) == set(MetaConfig().features)
