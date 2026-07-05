"""Score-CLI tests: the 'predict' half of the loop — log live watchlist scores, offline.

Also proves the full predict->resolve loop is CLOSED: run_score_watchlist logs predictions →
run_resolve_predictions resolves them → resolved_stats shows n_resolved > 0.
"""
from __future__ import annotations

import json
import sqlite3
import sys

import numpy as np
import pandas as pd

import scripts.run_score_watchlist as score_mod
from equity_scout.market import PricePanel
from equity_scout.ml.entry_features import FEATURE_COLUMNS
from equity_scout.ml.entry_model import train_entry_model
from equity_scout.ml.model_registry import promote_if_better, register_challenger
from equity_scout.ml.prediction_ledger import resolved_stats
from equity_scout.radar_storage import init_radar_db
from scripts.run_resolve_predictions import run_resolve_predictions
from scripts.run_score_watchlist import main, run_score_watchlist

STAMP = "2026-07-05T12:00:00+00:00"


def _panel(n: int = 400) -> PricePanel:
    """SPY + AAA (beats) + BBB (lags), all full history; CCC starts late (too little history)."""
    idx = pd.bdate_range("2019-01-01", periods=n)
    ccc = [np.nan] * (n - 40) + [100.0 * 1.001**i for i in range(40)]
    data = {
        "SPY": [100.0 * 1.0004**i for i in range(n)],
        "AAA": [100.0 * 1.0006**i for i in range(n)],
        "BBB": [100.0 * 1.0002**i for i in range(n)],
        "CCC": ccc,
    }
    return PricePanel(pd.DataFrame(data, index=idx))


def _now(panel: PricePanel, pos: int) -> str:
    return panel.dates[pos].isoformat()


def _promote_model(db: str) -> int:
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(20, len(FEATURE_COLUMNS))), columns=list(FEATURE_COLUMNS))
    y = pd.Series((X[FEATURE_COLUMNS[0]] > 0.0).astype(int).to_numpy())
    version = register_challenger(
        db, train_entry_model(X, y), metrics={"auc": 0.7}, n_train=20, now=STAMP
    )
    promote_if_better(db, version)
    return version


def _seed_watchlist(db: str, tickers: list[str]) -> None:
    init_radar_db(db)
    data = json.dumps({"created_at": STAMP, "entries": [{"ticker": t} for t in tickers]})
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO watchlists (created_at, data) VALUES (?, ?)", (STAMP, data))


def test_score_logs_predictions_with_champion_version(tmp_path):
    db = str(tmp_path / "led.db")
    version = _promote_model(db)
    _seed_watchlist(db, ["AAA", "BBB"])
    panel = _panel()

    result = run_score_watchlist(db, panel=panel, now=_now(panel, 350))

    assert result["logged"] == 2
    assert result["model_version"] == version
    assert result["skipped"] == []
    # both landed in the append-only ledger, open (unresolved), tagged with the champion version
    assert resolved_stats(db, model_version=version)["n_open"] == 2


def test_score_no_champion_logs_zero_and_exits_ok(tmp_path):
    db = str(tmp_path / "led.db")
    _seed_watchlist(db, ["AAA"])
    panel = _panel()

    result = run_score_watchlist(db, panel=panel, now=_now(panel, 350))

    assert result == {"logged": 0}
    assert resolved_stats(db)["n_open"] == 0  # nothing logged without a champion


def test_score_skips_ticker_without_enough_history(tmp_path):
    db = str(tmp_path / "led.db")
    _promote_model(db)
    _seed_watchlist(db, ["AAA", "CCC"])
    panel = _panel()

    result = run_score_watchlist(db, panel=panel, now=_now(panel, 350))

    assert "CCC" in result["skipped"]  # < 252 history at as_of → skipped, never logged
    assert result["logged"] == 1


def test_score_no_watchlist_logs_zero(tmp_path):
    db = str(tmp_path / "led.db")
    _promote_model(db)
    panel = _panel()

    result = run_score_watchlist(db, panel=panel, now=_now(panel, 350))

    assert result == {"logged": 0}  # no watchlist → honest no-op


def test_score_main_happy_path_exits_zero(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "led.db")
    _promote_model(db)
    _seed_watchlist(db, ["AAA", "BBB"])
    monkeypatch.setattr(score_mod, "_load_panel", lambda tickers, start: _panel())
    monkeypatch.setattr(sys, "argv", ["run_score_watchlist.py", "--db", db])

    assert main() == 0
    assert resolved_stats(db)["n_open"] == 2
    assert "bewertet" in capsys.readouterr().out


def test_predict_resolve_loop_is_closed(tmp_path):
    """The proof the loop is wired end to end: score logs live predictions → the resolver fills the
    realized outcome against real forward prices → resolved_stats moves off zero."""
    db = str(tmp_path / "led.db")
    _promote_model(db)
    _seed_watchlist(db, ["AAA", "BBB"])
    panel = _panel()

    logged = run_score_watchlist(db, panel=panel, now=_now(panel, 350))
    assert logged["logged"] == 2
    assert resolved_stats(db)["n_resolved"] == 0  # freshly logged, nothing resolved yet

    resolved = run_resolve_predictions(
        db, now=_now(panel, 380), fetch_prices=lambda tickers, start: panel
    )
    assert resolved["resolved"] == 2
    assert resolved_stats(db)["n_resolved"] == 2  # loop closed: predictions resolved vs prices
