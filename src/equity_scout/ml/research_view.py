"""Summarise the research ledger for the dashboard: champion, leaderboard, the rising overfitting
hurdle, and which dimensions are winning (model + feature frequency among the top configs). Pure read
over the ledger so the Forschung tab reflects the background loop live."""
from __future__ import annotations

import os
from collections import Counter

from equity_scout.metrics import expected_max_sharpe
from equity_scout.ml.ledger import TrialRecord, load_trials
from equity_scout.ml.pbo import load_pbo
from equity_scout.ml.strategy_ledger import StrategyTrialRecord, load_strategy_trials
from equity_scout.ml.strategy_search import all_configs, build_strategy


def _record_to_dict(record: TrialRecord) -> dict:
    config = record.config
    return {
        "features": list(config.features),
        "model": config.model,
        "primary_lookback_months": config.primary_lookback_months,
        "horizon_days": config.horizon_days,
        "barrier": config.barrier,
        "dsr": record.dsr,
        "sharpe": round(record.sharpe, 3),
        "sortino": round(record.sortino, 3),
        "cagr": round(record.cagr, 4),
        "max_drawdown": round(record.max_drawdown, 4),
        "oos_hit_rate": round(record.oos_hit_rate, 3),
        "n_bets": record.n_bets,
        "feature_importance": record.feature_importance,
    }


def research_summary(db_path: str, *, top_n: int = 8) -> dict:
    strategy_block = strategy_search_summary(db_path)
    if not os.path.exists(db_path):
        return {"available": False, "n_trials": 0, "champion": None, "leaderboard": [],
                "strategy_search": strategy_block}
    records = load_trials(db_path)
    if not records:
        return {"available": True, "n_trials": 0, "champion": None, "leaderboard": [],
                "strategy_search": strategy_block}

    ranked = sorted(records, key=lambda r: (r.dsr, r.sharpe), reverse=True)
    top = ranked[:top_n]
    model_freq = Counter(r.config.model for r in top)
    feature_freq = Counter(feat for r in top for feat in r.config.features)
    summary = {
        "available": True,
        "n_trials": len(records),
        "hurdle": round(expected_max_sharpe([r.sharpe_periodic for r in records]), 4),
        "champion": _record_to_dict(ranked[0]),
        "leaderboard": [_record_to_dict(r) for r in top],
        "model_frequency": dict(model_freq),
        "feature_frequency": dict(feature_freq),
    }
    pbo = load_pbo(db_path)  # second overfitting diagnostic, computed on demand via scripts/run_pbo.py
    if pbo is not None:
        summary["pbo"] = pbo
    summary["strategy_search"] = strategy_block
    return summary


def _strategy_record_to_dict(record: StrategyTrialRecord) -> dict:
    return {
        "strategy": record.config.strategy,
        "name": build_strategy(record.config).name,
        "params": record.config.params_dict(),
        "dsr": record.dsr,
        "dsr_hurdle": record.dsr_hurdle,
        "sharpe": round(record.sharpe, 3),
        "sortino": round(record.sortino, 3),
        "cagr": round(record.cagr, 4),
        "max_drawdown": round(record.max_drawdown, 4),
        "annual_turnover": round(record.annual_turnover, 2),
    }


def strategy_search_summary(db_path: str, *, top_n: int = 5) -> dict:
    """The v14 strategy-parameter pool: OWN trial count and OWN hurdle (never mixed with
    the ML pool above). In-sample whole-history backtests, DSR-deflated — evidence for
    Nico, never auto-promoted into the live sleeves."""
    space_size = len(all_configs())
    if not os.path.exists(db_path):
        return {"available": False, "n_trials": 0, "space_size": space_size,
                "champion": None, "leaderboard": [], "best_per_strategy": []}
    records = load_strategy_trials(db_path)
    if not records:
        return {"available": True, "n_trials": 0, "space_size": space_size,
                "champion": None, "leaderboard": [], "best_per_strategy": []}
    ranked = sorted(records, key=lambda r: (r.dsr, r.sharpe), reverse=True)
    best_per: dict[str, StrategyTrialRecord] = {}
    for record in ranked:
        best_per.setdefault(record.config.strategy, record)
    return {
        "available": True,
        "n_trials": len(records),
        "space_size": space_size,
        "hurdle": round(expected_max_sharpe([r.sharpe_periodic for r in records]), 4),
        "champion": _strategy_record_to_dict(ranked[0]),
        "leaderboard": [_strategy_record_to_dict(r) for r in ranked[:top_n]],
        "best_per_strategy": [_strategy_record_to_dict(r) for r in best_per.values()],
    }
