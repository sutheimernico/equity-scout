"""CLI: compute the Probability of Backtest Overfitting (PBO) over the top ledger configs.

Re-runs the out-of-sample equity for the top-N configs (by Deflated Sharpe) plus the default, slices
each into time blocks, and runs CSCV (combinatorially-symmetric cross-validation). Persists the result
so the Auto-Research tab can show it. Slow — one walk-forward per config — so run it occasionally, not
in the loop. A second, independent overfitting check alongside the Deflated Sharpe hurdle.

PAPER / RESEARCH ONLY.
"""
from __future__ import annotations

import argparse
from datetime import date

from equity_scout.constants import DISCLAIMER
from equity_scout.data.etf_panel import load_etf_panel
from equity_scout.etf_universe import ETF_TICKERS
from equity_scout.ml.ledger import DEFAULT_LEDGER_PATH, load_trials
from equity_scout.ml.meta_model import DEFAULT_CONFIG
from equity_scout.ml.pbo import block_sharpe_matrix, probability_of_backtest_overfitting, save_pbo


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_LEDGER_PATH, help="Research ledger DB path.")
    ap.add_argument("--top", type=int, default=12, help="How many top configs (by DSR) to include.")
    ap.add_argument("--blocks", type=int, default=8, help="Number of time blocks for CSCV.")
    ap.add_argument("--start", default="2007-01-01", help="Panel start date (first fetch only).")
    ap.add_argument("--refresh", action="store_true", help="Re-fetch the price panel from yfinance.")
    args = ap.parse_args()

    panel = load_etf_panel(ETF_TICKERS, start=args.start, refresh=args.refresh)
    records = sorted(load_trials(args.db), key=lambda r: (r.dsr, r.sharpe), reverse=True)
    configs = [DEFAULT_CONFIG] + [r.config for r in records[: args.top]]
    print(f"\nPBO over {len(configs)} configs, {args.blocks} blocks — running walk-forwards…\n")

    matrix, kept = block_sharpe_matrix(panel, configs, n_blocks=args.blocks)
    pbo = probability_of_backtest_overfitting(matrix)
    save_pbo(args.db, pbo=pbo, n_configs=len(kept), n_blocks=args.blocks, computed_at=date.today().isoformat())

    print(f"PBO = {pbo:.2f}  (over {len(kept)} usable configs)")
    print("Lesart: niedrig = die Bestenliste ist eher Können; hoch (→ 0.5+) = eher Glück.\n")
    print(DISCLAIMER)


if __name__ == "__main__":
    main()
