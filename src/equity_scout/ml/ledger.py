"""Persistent trial ledger for the research loop (SQLite).

Each distinct configuration is one row (config_key is the primary key → re-evaluating the same point
overwrites, so the trial count reflects *unique* configs tried, never inflated by repeats). The DSR
is NOT stored — it is recomputed from all trials' Sharpes whenever asked, so the overfitting hurdle
rises automatically as the search widens. The champion is the config with the highest current DSR.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from equity_scout.metrics import expected_max_sharpe, psr_from_stats
from equity_scout.ml.meta_model import MetaConfig
from equity_scout.ml.search import MIN_BETS, EvalResult

DEFAULT_LEDGER_PATH = "research_ledger.db"


@dataclass(frozen=True)
class TrialRecord:
    config: MetaConfig
    n_bets: int
    oos_hit_rate: float
    sharpe_periodic: float
    n_obs: int
    skew: float
    kurtosis: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    feature_importance: dict[str, float]
    dsr: float = 0.0  # computed against the whole ledger, not stored


def init_ledger(db_path: str = DEFAULT_LEDGER_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS loop_state (id INTEGER PRIMARY KEY CHECK (id = 1), next_index INTEGER NOT NULL)"
        )
        conn.execute("INSERT OR IGNORE INTO loop_state (id, next_index) VALUES (1, 0)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trials (
                config_key TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                n_bets INTEGER NOT NULL,
                oos_hit_rate REAL NOT NULL,
                sharpe_periodic REAL NOT NULL,
                n_obs INTEGER NOT NULL,
                skew REAL NOT NULL,
                kurtosis REAL NOT NULL,
                cagr REAL NOT NULL,
                sharpe REAL NOT NULL,
                sortino REAL NOT NULL,
                max_drawdown REAL NOT NULL,
                feature_importance TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


def _config_json(config: MetaConfig) -> str:
    return json.dumps({
        "features": list(config.features),
        "model": config.model,
        "primary_lookback_months": config.primary_lookback_months,
        "horizon_days": config.horizon_days,
        "barrier": config.barrier,
    })


def _config_from_json(text: str) -> MetaConfig:
    d = json.loads(text)
    return MetaConfig(
        features=tuple(d["features"]),
        model=d["model"],
        primary_lookback_months=d["primary_lookback_months"],
        horizon_days=d["horizon_days"],
        barrier=d["barrier"],
    )


def record_trial(db_path: str, result: EvalResult, *, now: str) -> None:
    """Upsert one evaluated config. Untrained / too-few-bets results are skipped (not real trials)."""
    if not result.trained or result.n_bets < MIN_BETS:
        return
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO trials VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(config_key) DO UPDATE SET
                 config_json=excluded.config_json, n_bets=excluded.n_bets,
                 oos_hit_rate=excluded.oos_hit_rate, sharpe_periodic=excluded.sharpe_periodic,
                 n_obs=excluded.n_obs, skew=excluded.skew, kurtosis=excluded.kurtosis,
                 cagr=excluded.cagr, sharpe=excluded.sharpe, sortino=excluded.sortino,
                 max_drawdown=excluded.max_drawdown, feature_importance=excluded.feature_importance,
                 created_at=excluded.created_at""",
            (
                result.config.key(), _config_json(result.config), result.n_bets,
                result.oos_hit_rate, result.sharpe_periodic, result.n_obs, result.skew,
                result.kurtosis, result.cagr, result.sharpe, result.sortino, result.max_drawdown,
                json.dumps(result.feature_importance), now,
            ),
        )


def load_trials(db_path: str) -> list[TrialRecord]:
    """All trials, each with its DSR recomputed against the current trial set (hurdle rises with N)."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM trials").fetchall()
    if not rows:
        return []
    hurdle = expected_max_sharpe([r["sharpe_periodic"] for r in rows])
    records = []
    for r in rows:
        dsr = psr_from_stats(r["sharpe_periodic"], r["n_obs"], r["skew"], r["kurtosis"], hurdle)
        records.append(TrialRecord(
            config=_config_from_json(r["config_json"]),
            n_bets=r["n_bets"], oos_hit_rate=r["oos_hit_rate"],
            sharpe_periodic=r["sharpe_periodic"], n_obs=r["n_obs"], skew=r["skew"],
            kurtosis=r["kurtosis"], cagr=r["cagr"], sharpe=r["sharpe"], sortino=r["sortino"],
            max_drawdown=r["max_drawdown"], feature_importance=json.loads(r["feature_importance"]),
            dsr=round(dsr, 4),
        ))
    return records


def trial_count(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM trials").fetchone()[0])


def current_hurdle(db_path: str) -> float:
    """The DSR deflation Sharpe given how many configs have been tried — the overfitting budget."""
    with sqlite3.connect(db_path) as conn:
        sharpes = [row[0] for row in conn.execute("SELECT sharpe_periodic FROM trials").fetchall()]
    return round(expected_max_sharpe(sharpes), 4)


def champion(db_path: str) -> TrialRecord | None:
    """The config with the highest current Deflated Sharpe (best survivor of the search)."""
    records = load_trials(db_path)
    return max(records, key=lambda r: r.dsr) if records else None


def next_index(db_path: str) -> int:
    """The trial index to evaluate next — persisted so a restart resumes where it stopped."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT next_index FROM loop_state WHERE id = 1").fetchone()
    return int(row[0]) if row else 0


def advance_index(db_path: str, to_index: int) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE loop_state SET next_index = ? WHERE id = 1", (to_index,))
