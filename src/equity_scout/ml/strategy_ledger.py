"""Persistent trial ledger for the STRATEGY-parameter search (v14, P7/v5-P4).

Own tables (`strategy_trials`, `strategy_loop_state`) in the same research_ledger.db
file, deliberately SEPARATE from the ML meta-model ledger (`ledger.py`): the two
searches must never share one multiple-testing accounting — the ML pool's breadth must
not deflate the strategy pool's Sharpes or vice versa. Same bookkeeping conventions as
`ledger.py`: config_key is the primary key (trial count = unique configs, upserts keep
metrics fresh as the panel grows), the DSR is recomputed on read against THIS pool only,
and `dsr_hurdle` stores the bar in force when the trial was recorded (v13 Q2 pattern —
here from birth, no migration needed).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from equity_scout.metrics import expected_max_sharpe, psr_from_stats
from equity_scout.ml.ledger import DEFAULT_LEDGER_PATH
from equity_scout.ml.strategy_search import StrategyConfig, StrategyEvalResult


@dataclass(frozen=True)
class StrategyTrialRecord:
    config: StrategyConfig
    sharpe_periodic: float
    n_obs: int
    skew: float
    kurtosis: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    annual_turnover: float
    dsr: float = 0.0  # recomputed against the strategy pool, never stored
    dsr_hurdle: float | None = None  # the bar in force at record time, stored verbatim


def init_strategy_ledger(db_path: str = DEFAULT_LEDGER_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS strategy_loop_state"
            " (id INTEGER PRIMARY KEY CHECK (id = 1), next_index INTEGER NOT NULL)"
        )
        conn.execute("INSERT OR IGNORE INTO strategy_loop_state (id, next_index) VALUES (1, 0)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_trials (
                config_key TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                sharpe_periodic REAL NOT NULL,
                n_obs INTEGER NOT NULL,
                skew REAL NOT NULL,
                kurtosis REAL NOT NULL,
                cagr REAL NOT NULL,
                sharpe REAL NOT NULL,
                sortino REAL NOT NULL,
                max_drawdown REAL NOT NULL,
                annual_turnover REAL NOT NULL,
                created_at TEXT NOT NULL,
                dsr_hurdle REAL
            )
        """)


def _config_from_json(text: str) -> StrategyConfig:
    d = json.loads(text)
    params = tuple(
        sorted((name, tuple(v) if isinstance(v, list) else v) for name, v in d["params"].items())
    )
    return StrategyConfig(strategy=d["strategy"], params=params)


def record_strategy_trial(
    db_path: str, result: StrategyEvalResult, *, now: str, dsr_hurdle: float | None = None
) -> None:
    """Upsert one evaluated config. `dsr_hurdle` is the hurdle in force BEFORE this trial
    landed — pass what the loop read first; stored verbatim, never recomputed."""
    key = result.config.key()  # canonical JSON — serves as PK and payload alike
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO strategy_trials (
                 config_key, config_json, sharpe_periodic, n_obs, skew, kurtosis,
                 cagr, sharpe, sortino, max_drawdown, annual_turnover, created_at, dsr_hurdle
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(config_key) DO UPDATE SET
                 config_json=excluded.config_json, sharpe_periodic=excluded.sharpe_periodic,
                 n_obs=excluded.n_obs, skew=excluded.skew, kurtosis=excluded.kurtosis,
                 cagr=excluded.cagr, sharpe=excluded.sharpe, sortino=excluded.sortino,
                 max_drawdown=excluded.max_drawdown, annual_turnover=excluded.annual_turnover,
                 created_at=excluded.created_at, dsr_hurdle=excluded.dsr_hurdle""",
            (
                key, key, result.sharpe_periodic,
                result.n_obs, result.skew, result.kurtosis, result.cagr, result.sharpe,
                result.sortino, result.max_drawdown, result.annual_turnover, now, dsr_hurdle,
            ),
        )


def load_strategy_trials(db_path: str) -> list[StrategyTrialRecord]:
    """All strategy trials, DSR recomputed against the CURRENT strategy pool only."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM strategy_trials").fetchall()
        except sqlite3.OperationalError:  # pre-v14 ledger, read-only consumer: no table
            return []
    if not rows:
        return []
    hurdle = expected_max_sharpe([r["sharpe_periodic"] for r in rows])
    return [
        StrategyTrialRecord(
            config=_config_from_json(r["config_json"]),
            sharpe_periodic=r["sharpe_periodic"], n_obs=r["n_obs"], skew=r["skew"],
            kurtosis=r["kurtosis"], cagr=r["cagr"], sharpe=r["sharpe"], sortino=r["sortino"],
            max_drawdown=r["max_drawdown"], annual_turnover=r["annual_turnover"],
            dsr=round(
                psr_from_stats(r["sharpe_periodic"], r["n_obs"], r["skew"], r["kurtosis"], hurdle),
                4,
            ),
            dsr_hurdle=r["dsr_hurdle"],
        )
        for r in rows
    ]


def strategy_trial_count(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        try:
            return int(conn.execute("SELECT COUNT(*) FROM strategy_trials").fetchone()[0])
        except sqlite3.OperationalError:
            return 0


def current_strategy_hurdle(db_path: str) -> float:
    """The deflation Sharpe for the STRATEGY pool — its own overfitting budget."""
    with sqlite3.connect(db_path) as conn:
        try:
            sharpes = [
                row[0]
                for row in conn.execute("SELECT sharpe_periodic FROM strategy_trials").fetchall()
            ]
        except sqlite3.OperationalError:
            return 0.0
    return round(expected_max_sharpe(sharpes), 4)


def strategy_champion(db_path: str) -> StrategyTrialRecord | None:
    """Highest current DSR in the strategy pool. Evidence for Nico, never auto-promoted —
    changed parameters are a new strategy identity (see strategy_search docstring)."""
    records = load_strategy_trials(db_path)
    return max(records, key=lambda r: r.dsr) if records else None


def next_strategy_index(db_path: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT next_index FROM strategy_loop_state WHERE id = 1").fetchone()
    return int(row[0]) if row else 0


def advance_strategy_index(db_path: str, to_index: int) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE strategy_loop_state SET next_index = ? WHERE id = 1", (to_index,))
