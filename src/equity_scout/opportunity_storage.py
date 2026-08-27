"""Gemeldete Chancen — der Verlauf, den die App zeigt und an dem sich messen lässt.

Warum überhaupt gespeichert: eine Benachrichtigung, die verschickt und vergessen wird, ist
nicht überprüfbar. Mit dieser Tabelle kann später jede Meldung gegen den späteren Kurs
gehalten werden (`suggestion_review` macht das für die Vorschlagsliste; hier liegt das
Material für dasselbe auf Meldungsebene) — und die App kann zeigen, was gestern kam, ohne
dass Nico im Telegram-Verlauf scrollen muss.

`notified_at` ist zugleich die Cooldown-Quelle: `last_notified_at(ticker)` beantwortet
„haben wir den in den letzten sieben Tagen schon gemeldet".
"""
from __future__ import annotations

import json

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.db import connect

_COLUMNS = (
    "id, ticker, name, notified_at, headline, one_liner, verdict, why_now, risk, "
    "plan_line, score, stance, price, currency, buy_limit, horizon, explained_by, "
    "track_record, channels"
)


def init_opportunity_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                name TEXT,
                notified_at TEXT NOT NULL,
                headline TEXT NOT NULL,
                one_liner TEXT NOT NULL,
                verdict TEXT,
                why_now TEXT NOT NULL,
                risk TEXT NOT NULL,
                plan_line TEXT,
                score INTEGER,
                stance TEXT,
                price REAL,
                currency TEXT,
                buy_limit REAL,
                horizon TEXT,
                explained_by TEXT,
                track_record TEXT,
                channels TEXT
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_opportunities_ticker "
            "ON opportunities(ticker, notified_at DESC)"
        )


def record_opportunity(
    db_path: str,
    opportunity: dict,
    *,
    notified_at: str,
    channels: dict | None = None,
) -> int:
    init_opportunity_db(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO opportunities
                   (ticker, name, notified_at, headline, one_liner, verdict, why_now, risk,
                    plan_line, score, stance, price, currency, buy_limit, horizon,
                    explained_by, track_record, channels)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                opportunity["ticker"],
                opportunity.get("name"),
                notified_at,
                opportunity["headline"],
                opportunity["one_liner"],
                opportunity.get("verdict"),
                json.dumps(opportunity.get("why_now") or [], ensure_ascii=False),
                opportunity["risk"],
                opportunity.get("plan_line"),
                opportunity.get("score"),
                opportunity.get("stance"),
                opportunity.get("price"),
                opportunity.get("currency"),
                opportunity.get("limit"),
                opportunity.get("horizon"),
                opportunity.get("explained_by"),
                opportunity.get("track_record"),
                json.dumps(channels or {}, ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid or 0)


def _row_to_dict(row: tuple) -> dict:
    keys = [c.strip() for c in _COLUMNS.split(",")]
    item = dict(zip(keys, row, strict=True))
    item["why_now"] = json.loads(item["why_now"] or "[]")
    item["channels"] = json.loads(item["channels"] or "{}")
    return item


def recent_opportunities(db_path: str = DEFAULT_DB_PATH, *, limit: int = 30) -> list[dict]:
    init_opportunity_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM opportunities ORDER BY notified_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def last_notified_at(db_path: str, ticker: str) -> str | None:
    init_opportunity_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT notified_at FROM opportunities WHERE ticker = ? "
            "ORDER BY notified_at DESC LIMIT 1",
            (ticker,),
        ).fetchone()
    return row[0] if row else None
