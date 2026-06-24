"""The research loop: sample a config, evaluate it out-of-sample, record it, advance the cursor.

This is the "always learning in the background" engine. One iteration = `run_one_trial`. The CLI runs
it forever (sleep between trials); a fresh process resumes from the persisted cursor. It does not get
better by re-running on the same data — it gets better by *searching wider while the DSR hurdle rises
with every trial*, so luck cannot survive. That distinction is the whole point.
"""
from __future__ import annotations

from equity_scout.market import PricePanel
from equity_scout.ml.ledger import advance_index, init_ledger, next_index, record_trial
from equity_scout.ml.search import EvalResult, evaluate_config, sample_config


def run_one_trial(panel: PricePanel, db_path: str, trial_index: int, *, now: str) -> EvalResult:
    config = sample_config(trial_index)
    result = evaluate_config(panel, config)
    record_trial(db_path, result, now=now)  # no-op if untrained / too few bets
    return result


def run_research(panel: PricePanel, db_path: str, *, n_trials: int, now: str) -> int:
    """Run `n_trials` from the persisted cursor. Returns the new cursor. Resumable across restarts."""
    init_ledger(db_path)
    start = next_index(db_path)
    for index in range(start, start + n_trials):
        run_one_trial(panel, db_path, index, now=now)
        advance_index(db_path, index + 1)
    return next_index(db_path)
