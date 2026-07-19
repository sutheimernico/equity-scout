"""Tiny key-value app state in the main DB (send idempotency, monthly gates).

Same idiom as the other *_storage modules: init_state_db is idempotent and
called at the top of every public function, one sqlite3.connect per call.
Values are plain strings — callers format dates as ISO so lexicographic
comparison stays chronologically correct (e.g. digest_sent_on, core_plan_month).
"""
from __future__ import annotations

import sqlite3

from equity_scout.constants import DEFAULT_DB_PATH


def init_state_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )


def get_state(db_path: str, *, key: str) -> str | None:
    init_state_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_state(db_path: str, *, key: str, value: str) -> None:
    init_state_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
