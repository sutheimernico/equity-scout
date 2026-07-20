"""Central SQLite connection conventions (v12 R2, review 2026-07-20).

Three independent schedulers (nightly chain, daily chain, */15 crons) write the same
databases behind flocks that do not see each other. Default sqlite connections carry
busy_timeout=0, so the losing writer crashes with OperationalError instead of waiting.
Storage modules therefore connect through here: WAL (readers never block on the writer)
plus a 30s busy timeout (writers queue up instead of crashing).
"""
from __future__ import annotations

import sqlite3

BUSY_TIMEOUT_MS = 30_000


def connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_MS / 1000)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return con
