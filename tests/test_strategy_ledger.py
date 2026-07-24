"""v14 strategy ledger: own tables, own DSR pool, verbatim hurdle, resumable wrap-around
cursor — and strict separation from the ML meta-model ledger in the same DB file."""
from __future__ import annotations

import numpy as np
import pandas as pd

from equity_scout.market import PricePanel
from equity_scout.ml.ledger import current_hurdle, init_ledger, record_trial
from equity_scout.ml.meta_model import MetaConfig
from equity_scout.ml.search import EvalResult
from equity_scout.ml.strategy_ledger import (
    current_strategy_hurdle,
    init_strategy_ledger,
    load_strategy_trials,
    next_strategy_index,
    record_strategy_trial,
    strategy_champion,
    strategy_trial_count,
)
from equity_scout.ml.strategy_research_loop import run_strategy_research
from equity_scout.ml.strategy_search import StrategyConfig, StrategyEvalResult, all_configs


def _result(strategy: str, params: tuple, sharpe_periodic: float) -> StrategyEvalResult:
    return StrategyEvalResult(
        config=StrategyConfig(strategy=strategy, params=params),
        sharpe_periodic=sharpe_periodic, n_obs=2500, skew=0.0, kurtosis=3.0,
        cagr=0.06, sharpe=sharpe_periodic * 15.87, sortino=1.0, max_drawdown=-0.15,
        annual_turnover=1.2,
    )


def _ml_eval(sharpe_periodic: float, model: str = "elastic_net") -> EvalResult:
    return EvalResult(
        config=MetaConfig(features=("vol", "trend"), model=model),
        trained=True, n_bets=50, oos_hit_rate=0.6, sharpe_periodic=sharpe_periodic,
        n_obs=2000, skew=0.0, kurtosis=3.0, cagr=0.08, sharpe=sharpe_periodic * 15.87,
        sortino=1.0, max_drawdown=-0.2, feature_importance={"vol": 1.0},
    )


def test_roundtrip_preserves_tuple_params(tmp_path):
    db = str(tmp_path / "l.db")
    init_strategy_ledger(db)
    record_strategy_trial(
        db, _result("sector_rotation", (("lookback_months", (12, 6)), ("top_n", 3)), 0.04),
        now="t1", dsr_hurdle=0.02,
    )
    records = load_strategy_trials(db)
    assert len(records) == 1
    assert records[0].config.params_dict()["lookback_months"] == (12, 6)
    assert records[0].dsr_hurdle == 0.02
    assert 0.0 <= records[0].dsr <= 1.0


def test_upsert_keeps_trial_count_at_unique_configs(tmp_path):
    db = str(tmp_path / "l.db")
    init_strategy_ledger(db)
    params = (("lookback_months", 12),)
    record_strategy_trial(db, _result("gem", params, 0.03), now="t1")
    record_strategy_trial(db, _result("gem", params, 0.05), now="t2")  # re-evaluated later
    assert strategy_trial_count(db) == 1
    assert load_strategy_trials(db)[0].sharpe_periodic == 0.05  # metrics stay fresh


def test_hurdle_rises_with_the_strategy_pool_only(tmp_path):
    """The whole point of P7: the two searches never share one multiple-testing account."""
    db = str(tmp_path / "l.db")
    init_ledger(db)
    init_strategy_ledger(db)
    record_strategy_trial(db, _result("gem", (("lookback_months", 12),), 0.03), now="t1")
    assert current_strategy_hurdle(db) == 0.0  # one trial -> no deflation yet

    # ML trials land in the SAME file but must not move the strategy hurdle ...
    record_trial(db, _ml_eval(0.02), now="t1")
    record_trial(db, _ml_eval(0.09, model="random_forest"), now="t2")
    assert current_strategy_hurdle(db) == 0.0
    ml_hurdle = current_hurdle(db)
    assert ml_hurdle > 0.0

    # ... and strategy trials must not move the ML hurdle.
    record_strategy_trial(db, _result("gem", (("lookback_months", 6),), 0.08), now="t2")
    record_strategy_trial(db, _result("daa", (("top_n", 2),), 0.01), now="t3")
    assert current_strategy_hurdle(db) > 0.0
    assert current_hurdle(db) == ml_hurdle


def test_champion_is_highest_dsr(tmp_path):
    db = str(tmp_path / "l.db")
    init_strategy_ledger(db)
    record_strategy_trial(db, _result("gem", (("lookback_months", 12),), 0.02), now="t1")
    record_strategy_trial(db, _result("gem", (("lookback_months", 6),), 0.07), now="t2")
    best = strategy_champion(db)
    assert best is not None
    assert best.config.params_dict()["lookback_months"] == 6


def test_readers_tolerate_a_pre_v14_ledger(tmp_path):
    """Read-only consumers (/api/research) must not crash or ALTER when only the ML
    ledger exists yet."""
    db = str(tmp_path / "l.db")
    init_ledger(db)  # ML tables only
    assert load_strategy_trials(db) == []
    assert strategy_trial_count(db) == 0
    assert current_strategy_hurdle(db) == 0.0
    assert strategy_champion(db) is None


def _panel(days: int = 300) -> PricePanel:
    idx = pd.bdate_range("2024-01-01", periods=days)
    rng = np.random.default_rng(11)
    spy = 100.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.01, days))
    ief = 100.0 * np.cumprod(1.0 + rng.normal(0.0001, 0.003, days))
    return PricePanel(pd.DataFrame({"SPY": spy, "IEF": ief}, index=idx))


def test_loop_is_resumable_and_wraps_modulo_the_space(tmp_path):
    db = str(tmp_path / "l.db")
    panel = _panel()
    cursor = run_strategy_research(panel, db, n_trials=2, now="t1")
    assert cursor == 2
    assert next_strategy_index(db) == 2
    assert strategy_trial_count(db) == 2

    # jump the cursor to the end of the space: the next trial re-evaluates config 0
    n = len(all_configs())
    from equity_scout.ml.strategy_ledger import advance_strategy_index

    advance_strategy_index(db, n)
    cursor = run_strategy_research(panel, db, n_trials=1, now="t2")
    assert cursor == n + 1
    assert strategy_trial_count(db) == 2  # wrapped onto config 0 -> upsert, no new row
