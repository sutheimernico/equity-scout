"""The strategy-parameter research loop (v14): enumerate the finite grid, backtest,
record against the strategy pool's OWN DSR hurdle, advance the cursor.

Sibling of `research_loop.py` with one deliberate difference: the space is finite, so the
cursor wraps modulo its size — once every config has been tried, further trials RE-evaluate
the same configs against the by-then longer price history (upsert per config_key). The
trial count therefore stays "unique configs" and the hurdle stays honest while the metrics
never go stale.
"""
from __future__ import annotations

from equity_scout.market import PricePanel
from equity_scout.ml.strategy_ledger import (
    advance_strategy_index,
    current_strategy_hurdle,
    init_strategy_ledger,
    next_strategy_index,
    record_strategy_trial,
)
from equity_scout.ml.strategy_search import (
    StrategyEvalResult,
    all_configs,
    evaluate_strategy_config,
)


def run_one_strategy_trial(
    panel: PricePanel, db_path: str, trial_index: int, *, now: str
) -> StrategyEvalResult:
    configs = all_configs()
    config = configs[trial_index % len(configs)]
    # hurdle BEFORE this trial lands — the bar it actually competed against (Q2 pattern)
    hurdle = current_strategy_hurdle(db_path)
    result = evaluate_strategy_config(panel, config)
    record_strategy_trial(db_path, result, now=now, dsr_hurdle=hurdle)
    return result


def run_strategy_research(panel: PricePanel, db_path: str, *, n_trials: int, now: str) -> int:
    """Run `n_trials` from the persisted cursor. Returns the new cursor. Resumable."""
    init_strategy_ledger(db_path)
    start = next_strategy_index(db_path)
    for index in range(start, start + n_trials):
        run_one_strategy_trial(panel, db_path, index, now=now)
        advance_strategy_index(db_path, index + 1)
    return next_strategy_index(db_path)
