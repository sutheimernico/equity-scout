"""SQLite persistence for Web Push subscriptions (one row = one installed phone/browser).

Same idiom as inbox_storage.py: raw sqlite3 through db.connect (WAL + busy timeout),
idempotent init, per-function connections. The endpoint URL is the primary key because
that is what the browser hands us and what identifies the push channel — re-subscribing
the same device is an upsert, not a duplicate.

Delivery health lives on the row (`last_ok_at`, `failures`, `last_error`) so the cockpit
can show "this phone has not received anything since X" instead of silently going quiet:
a subscription that stopped working is the single most likely way this whole notification
path fails, and it fails invisibly unless it is recorded.
"""
from __future__ import annotations

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.db import connect

_COLUMNS = "endpoint, p256dh, auth, label, created_at, last_ok_at, last_error, failures"


def init_push_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS push_subscriptions (
                endpoint TEXT PRIMARY KEY,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                label TEXT,
                created_at TEXT NOT NULL,
                last_ok_at TEXT,
                last_error TEXT,
                failures INTEGER NOT NULL DEFAULT 0
            )"""
        )


def save_subscription(
    db_path: str,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    label: str | None,
    created_at: str,
) -> None:
    """Upsert by endpoint. Re-subscribing resets the failure counter: the browser only
    hands out a fresh subscription when the old one is gone, so past failures say nothing
    about the new channel."""
    init_push_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO push_subscriptions
                   (endpoint, p256dh, auth, label, created_at, last_ok_at, last_error, failures)
               VALUES (?, ?, ?, ?, ?, NULL, NULL, 0)
               ON CONFLICT(endpoint) DO UPDATE SET
                   p256dh = excluded.p256dh,
                   auth = excluded.auth,
                   label = COALESCE(excluded.label, push_subscriptions.label),
                   failures = 0,
                   last_error = NULL""",
            (endpoint, p256dh, auth, label, created_at),
        )


def list_subscriptions(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    init_push_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM push_subscriptions ORDER BY created_at"
        ).fetchall()
    keys = [c.strip() for c in _COLUMNS.split(",")]
    return [dict(zip(keys, row, strict=True)) for row in rows]


def delete_subscription(db_path: str, endpoint: str) -> bool:
    init_push_db(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        return cursor.rowcount > 0


def record_success(db_path: str, endpoint: str, *, at: str) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE push_subscriptions SET last_ok_at = ?, failures = 0, last_error = NULL "
            "WHERE endpoint = ?",
            (at, endpoint),
        )


def record_failure(db_path: str, endpoint: str, *, error: str) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE push_subscriptions SET failures = failures + 1, last_error = ? "
            "WHERE endpoint = ?",
            (error[:500], endpoint),
        )
