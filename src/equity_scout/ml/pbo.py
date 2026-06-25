"""Probability of Backtest Overfitting (PBO) via Combinatorially-Symmetric Cross-Validation (CSCV).

Bailey & López de Prado's diagnostic: across all symmetric splits of the timeline into in-sample /
out-of-sample halves, how often is the config that looked best in-sample below-median out-of-sample?
A high PBO means "the leaderboard is mostly luck". This is a *second*, independent overfitting check
alongside the Deflated Sharpe hurdle the loop already applies.

The ledger only stores aggregate per-trial metrics, not a performance-over-time matrix — so rather
than rebuild the ledger, PBO is computed on demand: re-run the OOS equity for a handful of top configs,
slice each into time blocks, and run CSCV over the resulting (config × block) Sharpe matrix. Slower
(one walk-forward per config), hence a CLI that persists the result for the API to read.
"""
from __future__ import annotations

import json
import sqlite3
from itertools import combinations
from pathlib import Path

import numpy as np

from equity_scout.market import PricePanel
from equity_scout.metrics import daily_returns
from equity_scout.ml.meta_model import MetaConfig, run_meta_model


def block_sharpe_matrix(
    panel: PricePanel, configs: list[MetaConfig], *, n_blocks: int = 8, costs_bps: float = 10.0
) -> tuple[np.ndarray, list[MetaConfig]]:
    """Per-config OOS daily-return Sharpe in each of `n_blocks` equal time blocks. Returns the matrix
    (kept_configs × n_blocks) and the configs that produced a usable OOS series."""
    rows: list[list[float]] = []
    kept: list[MetaConfig] = []
    for config in configs:
        result = run_meta_model(panel, config, costs_bps=costs_bps)
        if not result.trained:
            continue
        active = result.exposure[result.exposure > 0]
        if active.empty:
            continue
        returns = daily_returns(result.equity).loc[active.index[0]:]
        if len(returns) < n_blocks * 2:
            continue
        blocks = np.array_split(returns.to_numpy(), n_blocks)
        rows.append([float(b.mean() / b.std()) if b.std() > 0 else 0.0 for b in blocks])
        kept.append(config)
    return np.asarray(rows, dtype=float), kept


def probability_of_backtest_overfitting(matrix: np.ndarray) -> float:
    """CSCV PBO ∈ [0, 1]. For each symmetric in-sample/out-of-sample split of the blocks, take the
    in-sample-best config and look at its out-of-sample rank; PBO is the fraction of splits where it
    lands below the out-of-sample median. NaN if the matrix is too small to split."""
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 2:
        return float("nan")
    n_strats, n_blocks = matrix.shape
    half = n_blocks // 2
    all_blocks = set(range(n_blocks))
    overfit = 0
    total = 0
    for is_blocks in combinations(range(n_blocks), half):
        oos_blocks = list(all_blocks - set(is_blocks))
        is_perf = matrix[:, list(is_blocks)].mean(axis=1)
        oos_perf = matrix[:, oos_blocks].mean(axis=1)
        best = int(np.argmax(is_perf))
        rank = int((oos_perf <= oos_perf[best]).sum())  # 1..n_strats (higher = better OOS)
        w = rank / (n_strats + 1)  # relative rank in (0, 1)
        if np.log(w / (1.0 - w)) <= 0.0:  # below-median OOS → overfit case
            overfit += 1
        total += 1
    return overfit / total if total else float("nan")


def _init(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE IF NOT EXISTS pbo (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)")


def save_pbo(db_path: str | Path, *, pbo: float, n_configs: int, n_blocks: int, computed_at: str) -> None:
    _init(db_path)
    payload = json.dumps({"pbo": pbo, "n_configs": n_configs, "n_blocks": n_blocks, "computed_at": computed_at})
    with sqlite3.connect(db_path) as con:
        con.execute(
            "INSERT INTO pbo (id, data) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (payload,),
        )


def load_pbo(db_path: str | Path) -> dict | None:
    with sqlite3.connect(db_path) as con:
        try:
            row = con.execute("SELECT data FROM pbo WHERE id = 1").fetchone()
        except sqlite3.OperationalError:
            return None
    return json.loads(row[0]) if row else None
