"""Matrix qualify: pooling the checkpoint must stream, and must not move a single digit.

The streaming rewrite exists because the grouping version was OOM-killed at 10.1 GiB on
2026-08-19, taking the whole WSL VM with it. Rewriting arithmetic under memory pressure is
exactly how a measurement artefact gets in, so bit-identity is asserted, not assumed.
"""
from __future__ import annotations

import importlib.util
import json
import random
import tracemalloc
from pathlib import Path

from equity_scout.matrix.grid import PooledCells, pool_cells

REPO_DIR = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location("rmq", REPO_DIR / "scripts" / "run_matrix_qualify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rmq = _load_script()

AXES = dict(asset_class="index", signal="momentum_up", threshold=0.002, slice="1min",
            hold_bars=1, cost_bps=2.0, context="none")


def _cell(ticker: str, **over) -> dict:
    base = dict(ticker=ticker, window="search", n=100, gross_bp=1.5, net_bp=0.5, t=2.0,
                hit_rate=0.55, **AXES)
    base.update(over)
    return base


def _write(tmp_path: Path, cells: list[dict]) -> Path:
    path = tmp_path / "cells.jsonl"
    path.write_text("".join(json.dumps(c) + "\n" for c in cells))
    return path


def test_pools_the_checkpoint_and_reports_its_tickers(tmp_path) -> None:
    path = _write(tmp_path, [_cell("SPY"), _cell("QQQ", n=300, net_bp=1.5)])
    pooled, tickers = rmq.pool_checkpoint(path, window="search")
    assert tickers == {"SPY", "QQQ"}
    assert len(pooled) == 1
    (cell,) = pooled
    assert cell["n"] == 400
    assert cell["tickers"] == 2
    # trade-weighted: (0.5*100 + 1.5*300) / 400
    assert cell["net_bp"] == (0.5 * 100 + 1.5 * 300) / 400


def test_resume_markers_and_other_windows_are_skipped(tmp_path) -> None:
    path = _write(tmp_path, [
        _cell("SPY"),
        {"ticker": "SPY", "complete": True},          # resume marker, carries no cell fields
        _cell("IWM", window="holdout"),               # a different window must not leak in
    ])
    pooled, tickers = rmq.pool_checkpoint(path, window="search")
    assert tickers == {"SPY"}
    assert pooled[0]["tickers"] == 1


def test_blank_lines_do_not_break_the_pass(tmp_path) -> None:
    path = tmp_path / "cells.jsonl"
    path.write_text(json.dumps(_cell("SPY")) + "\n\n" + json.dumps(_cell("QQQ")) + "\n")
    pooled, _ = rmq.pool_checkpoint(path, window="search")
    assert pooled[0]["tickers"] == 2


def test_streaming_accumulator_is_bit_identical_to_the_list_form() -> None:
    # The whole point of the rewrite: same sums, same order, same float bits. Includes the
    # unmeasurable (net_bp=None) and t=None branches, which are where a sloppy accumulator
    # would quietly diverge.
    rng = random.Random(20260819)
    for _ in range(200):
        cells = []
        for i in range(rng.randint(1, 40)):
            unmeasurable = rng.random() < 0.2
            no_t = rng.random() < 0.2
            cells.append(_cell(
                f"T{i}",
                n=rng.randint(1, 5000),
                gross_bp=rng.uniform(-30, 30),
                net_bp=None if unmeasurable else rng.uniform(-30, 30),
                t=None if (no_t or unmeasurable) else rng.uniform(-6, 6),
                hit_rate=rng.uniform(0, 1),
            ))
        expected = pool_cells(cells, **AXES)

        acc = PooledCells()
        for cell in cells:
            acc.add(cell)
        assert acc.pooled(**AXES) == expected  # exact equality, not approx


def test_all_unmeasurable_group_reports_none_not_zero() -> None:
    # A pool of nothing measurable must stay None: a 0.0 would read as "measured, no edge".
    cells = [_cell("SPY", net_bp=None, t=None), _cell("QQQ", net_bp=None, t=None)]
    out = pool_cells(cells, **AXES)
    assert out["net_bp"] is None and out["t"] is None and out["gross_bp"] is None
    assert out["n"] == 200 and out["tickers"] == 2 and out["tickers_measurable"] == 0


def test_memory_stays_with_the_groups_not_the_cells(tmp_path) -> None:
    # Regression guard for the actual 2026-08-19 failure: 40k cells collapsing into 4 groups
    # must not retain the cells. Grouping them first cost ~700 bytes each; accumulating costs
    # a few hundred bytes per GROUP. The bound is deliberately loose -- it only has to fail
    # loudly if someone reintroduces a per-cell list.
    cells = [
        _cell(f"T{i % 200}", threshold=0.001 * (i % 4), n=i % 900 + 1)
        for i in range(40_000)
    ]
    path = _write(tmp_path, cells)
    tracemalloc.start()
    pooled, _ = rmq.pool_checkpoint(path, window="search")
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert len(pooled) == 4
    assert peak < 2_000_000, f"peak {peak:,} bytes — cells are being retained again"
