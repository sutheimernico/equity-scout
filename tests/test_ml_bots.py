"""ML bot family: signed weights, short P&L/borrow/margin floor, registry families, bot decides."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from equity_scout.forward_paper import ForwardAccount, advance_account
from equity_scout.market import MarketView, PricePanel
from equity_scout.strategies.base import TargetWeight, normalise_weights, weights_dict
from equity_scout.strategies.ml_bot import MLLongStrategy, MLShortStrategy

NOW = "2026-07-13T12:00:00+00:00"


# --- signed weights ---------------------------------------------------------------


def test_target_weight_side_validation_and_sign():
    long = TargetWeight("AAA", 0.4)
    short = TargetWeight("BBB", 0.3, side="short")
    assert long.signed_weight == 0.4
    assert short.signed_weight == -0.3
    with pytest.raises(ValueError):
        TargetWeight("AAA", 0.4, side="hedge")
    with pytest.raises(ValueError):
        TargetWeight("AAA", -0.4)  # magnitude stays [0, 1]; direction only via side


def test_weights_dict_nets_long_against_short():
    weights = [TargetWeight("AAA", 0.5), TargetWeight("AAA", 0.2, side="short")]
    assert weights_dict(weights) == {"AAA": pytest.approx(0.3)}


def test_normalise_weights_scales_gross_exposure_down():
    raw = [TargetWeight("AAA", 0.8), TargetWeight("BBB", 0.8, side="short")]
    normalised = {(tw.ticker, tw.side): tw.weight for tw in normalise_weights(raw)}
    assert normalised[("AAA", "long")] == pytest.approx(0.5)
    assert normalised[("BBB", "short")] == pytest.approx(0.5)


# --- short P&L in the forward account ----------------------------------------------


class _FixedStrategy:
    name = "fixed"

    def __init__(self, targets: list[TargetWeight]):
        self._targets = targets

    def decide(self, as_of, market):
        return self._targets


def _two_day_panel(first: float, second: float) -> tuple[PricePanel, PricePanel]:
    idx = pd.bdate_range("2026-01-05", periods=2)
    day1 = PricePanel(pd.DataFrame({"AAA": [first], "SPY": [100.0]}, index=idx[:1]))
    day2 = PricePanel(
        pd.DataFrame({"AAA": [first, second], "SPY": [100.0, 100.0]}, index=idx)
    )
    return day1, day2


def _advanced_short_equity(second_price: float, *, borrow_bps: float = 0.0) -> float:
    day1, day2 = _two_day_panel(100.0, second_price)
    strategy = _FixedStrategy([TargetWeight("AAA", 0.5, side="short")])
    account = ForwardAccount.fresh("fixed", initial_capital=10_000.0)
    account, _ = advance_account(account, strategy, day1, costs_bps=0.0)
    account, _ = advance_account(
        account, strategy, day2, costs_bps=0.0, borrow_bps_per_day=borrow_bps
    )
    return account.equity


def test_short_position_gains_when_price_falls():
    assert _advanced_short_equity(90.0) == pytest.approx(10_000.0 * 1.05)  # -0.5 * -10 %


def test_short_position_loses_when_price_rises():
    assert _advanced_short_equity(110.0) == pytest.approx(10_000.0 * 0.95)


def test_borrow_cost_proxy_is_charged_on_short_gross():
    flat = _advanced_short_equity(100.0, borrow_bps=2.0)
    # flat price, 0.5 short gross, 2 bps/day, 1 trading day -> 1 bps on equity
    assert flat == pytest.approx(10_000.0 * (1.0 - 0.5 * 2.0 / 10_000.0))


def test_margin_floor_forces_liquidation_and_stays_dead():
    day1, day2 = _two_day_panel(100.0, 350.0)  # +250 % against a full short
    strategy = _FixedStrategy([TargetWeight("AAA", 1.0, side="short")])
    account = ForwardAccount.fresh("fixed", initial_capital=10_000.0)
    account, _ = advance_account(account, strategy, day1, costs_bps=0.0)
    account, valuation = advance_account(account, strategy, day2, costs_bps=0.0)

    assert account.equity == 0.0
    assert account.weights == {}
    assert valuation is not None and valuation.total_return == -1.0

    idx3 = pd.bdate_range("2026-01-05", periods=3)
    day3 = PricePanel(
        pd.DataFrame({"AAA": [100.0, 350.0, 50.0], "SPY": [100.0] * 3}, index=idx3)
    )
    dead, valuation = advance_account(account, strategy, day3, costs_bps=0.0)
    assert dead.equity == 0.0 and dead.weights == {} and valuation is None


# --- registry families ---------------------------------------------------------------


def test_registry_families_keep_separate_champions(tmp_path):
    from equity_scout.ml.model_registry import (
        entry_champion,
        promote_if_better,
        register_challenger,
        registry_summary,
    )
    from equity_scout.ml.entry_model import train_entry_model
    from equity_scout.ml.entry_features import FEATURE_COLUMNS

    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(60, len(FEATURE_COLUMNS))), columns=list(FEATURE_COLUMNS))
    y = pd.Series((X.iloc[:, 0] > 0).astype(int))
    model = train_entry_model(X, y, model="elastic_net")
    db = str(tmp_path / "registry.db")
    good = {"auc": 0.62, "n_oos": 250, "brier": 0.2}

    long_v = register_challenger(db, model, metrics=good, n_train=60, now=NOW)
    short_v = register_challenger(
        db, model, metrics=good, n_train=60, now=NOW, family="entry_short"
    )
    assert promote_if_better(db, long_v) is True
    assert promote_if_better(db, short_v) is True  # own family -> no delta fight with long

    long_champ = entry_champion(db, family="entry")
    short_champ = entry_champion(db, family="entry_short")
    assert long_champ is not None and long_champ[0] == long_v
    assert short_champ is not None and short_champ[0] == short_v
    summary = registry_summary(db)
    assert summary["champions"] == {"entry": long_v, "entry_short": short_v}
    assert summary["champion_version"] == long_v  # pre-family API contract


def test_backfill_dataset_lags_direction_inverts_label_and_return():
    from equity_scout.ml.entry_dataset import build_backfill_dataset

    n = 600
    idx = pd.bdate_range("2019-01-01", periods=n)
    panel = PricePanel(
        pd.DataFrame(
            {
                "SPY": [100.0 * 1.0004**i for i in range(n)],
                "AAA": [100.0 * 1.0006**i for i in range(n)],  # beats SPY always
            },
            index=idx,
        )
    )
    _, y_beats, meta_beats = build_backfill_dataset(panel, ["AAA"])
    _, y_lags, meta_lags = build_backfill_dataset(panel, ["AAA"], label_direction="lags")
    assert len(y_beats) == len(y_lags) > 0
    assert (y_beats == 1).all() and (y_lags == 0).all()
    assert np.allclose(
        meta_lags["relative_return"], -meta_beats["relative_return"]
    )


# --- bot decides ---------------------------------------------------------------------


class _StubModel:
    """Duck-typed champion stand-in: every scored row gets the same fixed 0-100 score."""

    def __init__(self, fixed: int = 80):
        self._fixed = fixed

    def score_row(self, features: dict) -> int:
        return self._fixed


def test_long_bot_without_champion_never_trades(wavy_panel):
    bot = MLLongStrategy(model=None, tickers=["VEU", "VWO"])
    view = MarketView(wavy_panel, wavy_panel.dates[-1])
    assert bot.ready is False
    assert bot.decide(view.as_of, view) == []


def test_long_bot_holds_top_scores_equal_weight(wavy_panel):
    bot = MLLongStrategy(
        model=_StubModel(fixed=80), tickers=["VEU", "VWO", "VNQ"], top_k=2, threshold=60
    )
    view = MarketView(wavy_panel, wavy_panel.dates[-1])
    targets = bot.decide(view.as_of, view)
    assert len(targets) == 2
    assert all(tw.side == "long" and tw.weight == pytest.approx(0.5) for tw in targets)


def test_long_bot_threshold_blocks_weak_scores(wavy_panel):
    bot = MLLongStrategy(model=_StubModel(fixed=40), tickers=["VEU", "VWO"], threshold=60)
    view = MarketView(wavy_panel, wavy_panel.dates[-1])
    assert bot.decide(view.as_of, view) == []


def test_short_bot_targets_are_short_at_reduced_exposure(wavy_panel):
    bot = MLShortStrategy(
        model=_StubModel(fixed=90), tickers=["VEU", "VWO"], top_k=2, threshold=60
    )
    view = MarketView(wavy_panel, wavy_panel.dates[-1])
    targets = bot.decide(view.as_of, view)
    assert len(targets) == 2
    assert all(tw.side == "short" for tw in targets)
    assert sum(tw.weight for tw in targets) == pytest.approx(0.5)  # DEFAULT_SHORT_EXPOSURE
