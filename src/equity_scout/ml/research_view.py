"""Summarise the research ledger for the dashboard: champion, leaderboard, the rising overfitting
hurdle, and which dimensions are winning (model + feature frequency among the top configs). Pure read
over the ledger so the Forschung tab reflects the background loop live."""
from __future__ import annotations

import os
from collections import Counter

from equity_scout.metrics import expected_max_sharpe
from equity_scout.ml.ledger import TrialRecord, load_trials
from equity_scout.ml.pbo import load_pbo


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
    if not os.path.exists(db_path):
        return {"available": False, "n_trials": 0, "champion": None, "leaderboard": []}
    records = load_trials(db_path)
    if not records:
        return {"available": True, "n_trials": 0, "champion": None, "leaderboard": []}

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
    return summary
