"""Tests for the research loop: search space, ledger, DSR hurdle, champion, resumable cursor."""
from __future__ import annotations

from equity_scout.ml.ledger import (
    advance_index,
    champion,
    current_hurdle,
    init_ledger,
    load_trials,
    next_index,
    record_trial,
    trial_count,
)
from equity_scout.ml.meta_model import DEFAULT_CONFIG, MetaConfig
from equity_scout.ml.research_loop import run_research
from equity_scout.ml.search import MIN_BETS, MODELS, EvalResult, evaluate_config, sample_config


def _eval(features, model, sharpe_periodic, *, n_bets=50, n_obs=2000) -> EvalResult:
    return EvalResult(
        config=MetaConfig(features=tuple(features), model=model),
        trained=True, n_bets=n_bets, oos_hit_rate=0.6, sharpe_periodic=sharpe_periodic,
        n_obs=n_obs, skew=0.0, kurtosis=3.0, cagr=0.08, sharpe=sharpe_periodic * 15.87,
        sortino=1.0, max_drawdown=-0.2, feature_importance={"vol": 1.0},
    )


# --- Search space ---
def test_sample_config_is_deterministic_and_valid():
    assert sample_config(7).key() == sample_config(7).key()
    for i in range(12):
        config = sample_config(i)
        assert config.model in MODELS
        assert len(config.features) >= 2


# --- Ledger (synthetic, fast — no ML) ---
def test_ledger_roundtrip(tmp_path):
    db = str(tmp_path / "l.db")
    init_ledger(db)
    record_trial(db, _eval(["vol", "trend"], "elastic_net", 0.05), now="t1")
    records = load_trials(db)
    assert len(records) == 1
    assert records[0].config.model == "elastic_net"
    assert 0.0 <= records[0].dsr <= 1.0


def test_ledger_round_trips_the_dsr_hurdle(tmp_path):
    """v13 Q2: the hurdle in force at trial time is stored verbatim and read back."""
    db = str(tmp_path / "l.db")
    init_ledger(db)
    record_trial(db, _eval(["vol", "trend"], "elastic_net", 0.05), now="t1", dsr_hurdle=0.42)
    record_trial(db, _eval(["breadth", "drawdown"], "random_forest", 0.07), now="t2")
    by_model = {r.config.model: r for r in load_trials(db)}
    assert by_model["elastic_net"].dsr_hurdle == 0.42
    assert by_model["random_forest"].dsr_hurdle is None  # not passed -> honest None


def test_ledger_migrates_pre_hurdle_schema(tmp_path):
    """v13 Q2: a ledger created before the dsr_hurdle column opens, migrates idempotently,
    and its old rows read back as None (the historical hurdle cannot be reconstructed)."""
    import json
    import sqlite3

    db = str(tmp_path / "old.db")
    with sqlite3.connect(db) as conn:  # the pre-v13 schema, positional insert and all
        conn.execute("""
            CREATE TABLE trials (
                config_key TEXT PRIMARY KEY, config_json TEXT NOT NULL, n_bets INTEGER NOT NULL,
                oos_hit_rate REAL NOT NULL, sharpe_periodic REAL NOT NULL, n_obs INTEGER NOT NULL,
                skew REAL NOT NULL, kurtosis REAL NOT NULL, cagr REAL NOT NULL,
                sharpe REAL NOT NULL, sortino REAL NOT NULL, max_drawdown REAL NOT NULL,
                feature_importance TEXT NOT NULL, created_at TEXT NOT NULL
            )
        """)
        config_json = json.dumps({
            "features": ["vol", "trend"], "model": "elastic_net",
            "primary_lookback_months": 12, "horizon_days": 20, "barrier": 1.0,
        })
        conn.execute(
            "INSERT INTO trials VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("k1", config_json, 50, 0.6, 0.05, 2000, 0.0, 3.0, 0.08, 0.8, 1.0, -0.2, "{}", "t0"),
        )
    # read-only consumers (/api/ml -> champion -> load_trials) hit the file BEFORE any
    # writer migrates it — reading must not crash and must not require a write
    pre_migration = load_trials(db)
    assert len(pre_migration) == 1 and pre_migration[0].dsr_hurdle is None
    init_ledger(db)  # migrates
    init_ledger(db)  # idempotent
    old_rows = load_trials(db)
    assert len(old_rows) == 1 and old_rows[0].dsr_hurdle is None
    record_trial(db, _eval(["breadth", "drawdown"], "random_forest", 0.07),
                 now="t1", dsr_hurdle=0.1)
    by_model = {r.config.model: r for r in load_trials(db)}
    assert by_model["random_forest"].dsr_hurdle == 0.1
    assert by_model["elastic_net"].dsr_hurdle is None


def test_ledger_is_idempotent_per_config(tmp_path):
    db = str(tmp_path / "l.db")
    init_ledger(db)
    record_trial(db, _eval(["vol", "trend"], "elastic_net", 0.05), now="t1")
    record_trial(db, _eval(["trend", "vol"], "elastic_net", 0.06), now="t2")  # same key → update
    assert trial_count(db) == 1
    assert load_trials(db)[0].sharpe_periodic == 0.06


def test_untrained_results_are_not_recorded(tmp_path):
    db = str(tmp_path / "l.db")
    init_ledger(db)
    bad = EvalResult(MetaConfig(), False, 3, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    record_trial(db, bad, now="t")
    assert trial_count(db) == 0


def test_champion_is_highest_deflated_sharpe(tmp_path):
    db = str(tmp_path / "l.db")
    init_ledger(db)
    record_trial(db, _eval(["vol", "trend"], "elastic_net", 0.02), now="t")  # weak
    record_trial(db, _eval(["breadth", "drawdown"], "random_forest", 0.09), now="t")  # strong
    assert champion(db).config.model == "random_forest"


def test_overfitting_hurdle_rises_with_more_trials(tmp_path):
    db = str(tmp_path / "l.db")
    init_ledger(db)
    record_trial(db, _eval(["vol", "trend"], "elastic_net", 0.02), now="t")
    record_trial(db, _eval(["breadth", "drawdown"], "random_forest", 0.06), now="t")
    hurdle_two = current_hurdle(db)
    # four genuinely distinct configs (distinct keys) → trial count grows to 6
    for feats, model, sharpe in [
        (["vol", "breadth"], "elastic_net", 0.03),
        (["trend", "drawdown"], "random_forest", 0.07),
        (["vol", "mom_3m"], "elastic_net", 0.04),
        (["trend", "mom_3m"], "random_forest", 0.05),
    ]:
        record_trial(db, _eval(feats, model, sharpe), now="t")
    assert trial_count(db) == 6
    assert current_hurdle(db) >= hurdle_two  # more trials → the deflation hurdle is at least as high


def test_cursor_persists(tmp_path):
    db = str(tmp_path / "l.db")
    init_ledger(db)
    assert next_index(db) == 0
    advance_index(db, 5)
    assert next_index(db) == 5


def test_research_summary_and_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from equity_scout.api import create_app
    from equity_scout.ml.research_view import research_summary

    db = str(tmp_path / "l.db")
    init_ledger(db)
    record_trial(db, _eval(["vol", "trend"], "elastic_net", 0.02), now="t")
    record_trial(db, _eval(["breadth", "drawdown"], "random_forest", 0.09), now="t")
    summary = research_summary(db)
    assert summary["available"] and summary["n_trials"] == 2
    assert summary["champion"]["model"] == "random_forest"  # higher DSR
    assert len(summary["leaderboard"]) == 2
    assert "random_forest" in summary["model_frequency"]

    body = TestClient(create_app(ledger=db)).get("/api/research").json()
    assert body["available"] is True
    assert body["champion"]["model"] == "random_forest"


def test_research_summary_without_ledger(tmp_path):
    from equity_scout.ml.research_view import research_summary

    assert research_summary(str(tmp_path / "nope.db"))["available"] is False


# --- End-to-end loop (uses the shared wavy panel) ---
def test_evaluate_config_trains_on_long_panel(wavy_panel):
    result = evaluate_config(wavy_panel, DEFAULT_CONFIG)
    assert result.trained
    assert result.n_bets >= MIN_BETS
    assert result.n_obs > 0


def test_run_research_accumulates_and_resumes(wavy_panel, tmp_path):
    db = str(tmp_path / "r.db")
    run_research(wavy_panel, db, n_trials=3, now="t1")
    assert next_index(db) == 3
    first_count = trial_count(db)
    run_research(wavy_panel, db, n_trials=2, now="t2")
    assert next_index(db) == 5  # resumed from the cursor
    assert trial_count(db) >= first_count
    assert champion(db) is not None  # at least one config trained on a 10y panel
