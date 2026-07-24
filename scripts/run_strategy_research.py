"""CLI: the strategy-parameter research loop (v14, P7). Enumerates the finite grid over
the rule strategies' knobs, backtests each config after costs, and records it to the
strategy ledger — a SEPARATE trial pool with its own Deflated-Sharpe hurdle, so the ML
search's breadth never deflates these results and vice versa.

IN-SAMPLE by construction (whole-history backtests, DSR-deflated). The champion is
evidence, never auto-promoted: changed parameters are a new strategy identity and would
rewrite the sleeves' forward track records.

Resumable: a restart continues from the cursor; past the end of the grid the cursor
wraps and re-evaluates configs against the longer history (upsert, count stays unique).
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from equity_scout.data.etf_panel import load_etf_panel
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.ml.strategy_ledger import (
    advance_strategy_index,
    current_strategy_hurdle,
    init_strategy_ledger,
    next_strategy_index,
    strategy_champion,
    strategy_trial_count,
)
from equity_scout.ml.strategy_research_loop import run_one_strategy_trial
from equity_scout.ml.strategy_search import all_configs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default="research_ledger.db")
    ap.add_argument("--trials", type=int, default=0, help="0 = run forever (Ctrl-C to stop)")
    ap.add_argument("--sleep", type=float, default=0.5, help="seconds between trials")
    ap.add_argument("--start", default="2007-01-01")
    args = ap.parse_args()

    panel = load_etf_panel(ETF_TICKERS, start=args.start)
    init_strategy_ledger(args.ledger)
    space = len(all_configs())
    print(
        f"Strategy-parameter loop over {len(panel.dates)} days, {space} configs."
        f" Ledger: {args.ledger}. Ctrl-C to stop.\n"
    )

    done = 0
    try:
        while args.trials == 0 or done < args.trials:
            index = next_strategy_index(args.ledger)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            result = run_one_strategy_trial(panel, args.ledger, index, now=now)
            advance_strategy_index(args.ledger, index + 1)
            done += 1

            champ = strategy_champion(args.ledger)
            champ_str = (
                f" | champion DSR {champ.dsr:.2f} [{champ.config.strategy}"
                f" {champ.config.params_dict()}]" if champ else ""
            )
            print(
                f"[{strategy_trial_count(args.ledger):>3}/{space} configs,"
                f" hurdle {current_strategy_hurdle(args.ledger):.3f}]"
                f" trial {index}: {result.config.strategy} {result.config.params_dict()}"
                f" → sharpe {result.sharpe:.2f}, turn/y {result.annual_turnover:.1f}{champ_str}"
            )
            if args.trials == 0 or done < args.trials:
                time.sleep(args.sleep)
    except KeyboardInterrupt:
        print("\nStopped. Ledger persisted — restart to resume from where it left off.")


if __name__ == "__main__":
    main()
