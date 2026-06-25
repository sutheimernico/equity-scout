"""CLI: the continuous research loop. Searches model configurations and records each to the SQLite
ledger, with a Deflated-Sharpe hurdle that rises as the search widens — so it gets better by
exploring, never by overfitting the same data. Resumable: a restart continues from the cursor.

Run it in the background so it keeps learning while your laptop is on:
    nohup uv run python scripts/run_research.py > research.log 2>&1 &
Stop with Ctrl-C (or kill); the ledger is persisted and the next run resumes.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from equity_scout.data.etf_panel import load_etf_panel
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.ml.ledger import (
    advance_index,
    champion,
    current_hurdle,
    init_ledger,
    next_index,
    trial_count,
)
from equity_scout.ml.research_loop import run_one_trial


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default="research_ledger.db")
    ap.add_argument("--trials", type=int, default=0, help="0 = run forever (Ctrl-C to stop)")
    ap.add_argument("--sleep", type=float, default=2.0, help="seconds between trials")
    ap.add_argument("--start", default="2007-01-01")
    args = ap.parse_args()

    panel = load_etf_panel(ETF_TICKERS, start=args.start)
    init_ledger(args.ledger)
    print(f"Research loop over {len(panel.dates)} days. Ledger: {args.ledger}. Ctrl-C to stop.\n")

    done = 0
    try:
        while args.trials == 0 or done < args.trials:
            index = next_index(args.ledger)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            result = run_one_trial(panel, args.ledger, index, now=now)
            advance_index(args.ledger, index + 1)
            done += 1

            outcome = (
                f"trained sharpe {result.sharpe:.2f}, {result.n_bets} bets"
                if result.trained
                else "skipped (too few OOS bets)"
            )
            champ = champion(args.ledger)
            champ_str = f" | champion DSR {champ.dsr:.2f} [{champ.config.model}]" if champ else ""
            print(
                f"[{trial_count(args.ledger):>3} kept, hurdle {current_hurdle(args.ledger):.3f}] "
                f"trial {index}: {result.config.model} {list(result.config.features)} → {outcome}{champ_str}"
            )
            if args.trials == 0 or done < args.trials:
                time.sleep(args.sleep)
    except KeyboardInterrupt:
        print("\nStopped. Ledger persisted — restart to resume from where it left off.")


if __name__ == "__main__":
    main()
