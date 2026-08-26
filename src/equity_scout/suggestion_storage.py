"""Persistenz für die Vorschlags-Rückschau (Nachtschicht 2026-08-27).

Ein Lauf = eine unveränderliche Zeile mit JSON-Nutzlast, dieselbe Form wie `watchlists`. Die
Rückschau wird NICHT fortgeschrieben, sondern jedes Mal neu gemessen: sonst würde ein
gespeicherter alter Wert gegen einen frisch gemessenen verglichen, und genau daran ist am
2026-08-11 der Champion-Vergleich zerbrochen.

Das Sammeln der Vorschläge liegt hier mit drin, weil es reines Lesen aus derselben DB ist —
und weil die Definition, WAS als Vorschlag zählt, an einer Stelle stehen muss.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from equity_scout.suggestion_review import Suggestion

# Nur die Ränge, die auf einer Oberfläche wirklich auftauchen. Platz 47 einer Rangliste ist
# kein Vorschlag, und ihn mitzumessen würde die Stichprobe mit Titeln fluten, die Nico nie
# gesehen hat.
RANK_CUTOFF = 5

# Vor diesem Datum lief der Screen auf einem Teil-Universum (42, dann 531 Titel). Diese Runs
# sind nicht dieselbe Maschine und gehören nicht in dieselbe Statistik.
FULL_UNIVERSE_FROM = "2026-07-14"
MIN_FULL_UNIVERSE = 5000


def init_db(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS suggestion_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                computed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )


def save_review(db_path: str | Path, computed_at: str, payload: dict) -> int:
    init_db(db_path)
    with sqlite3.connect(db_path) as con:
        cur = con.execute(
            "INSERT INTO suggestion_reviews (computed_at, payload) VALUES (?, ?)",
            (computed_at, json.dumps(payload)),
        )
        return int(cur.lastrowid or 0)


def load_latest_review(db_path: str | Path) -> dict | None:
    if not Path(db_path).exists():
        return None
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        try:
            row = con.execute(
                "SELECT computed_at, payload FROM suggestion_reviews ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None  # Tabelle noch nie angelegt — kein Fehler, nur noch keine Messung
    if row is None:
        return None
    payload = json.loads(row["payload"])
    payload["computed_at"] = row["computed_at"]
    return payload


def collect_pitch_suggestions(db_path: str | Path) -> list[Suggestion]:
    """Jeder Pitch ist ein Vorschlag — auch ein abgelaufener.

    Ausdrücklich OHNE Filter auf `status` oder `verdict`: nur die abgeschlossenen oder nur die
    grünen zu messen wäre die Auswahl der Ergebnisse, die man messen will.
    """
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT created_at, ticker, price, composite FROM pitches ORDER BY created_at"
        ).fetchall()
    return [
        Suggestion(
            source="pitch",
            ticker=row["ticker"],
            suggested_at=row["created_at"],
            score=float(row["composite"]) * 100,
            quoted_price=float(row["price"]),
        )
        for row in rows
    ]


def collect_rank_suggestions(
    db_path: str | Path, *, cutoff: int = RANK_CUTOFF
) -> list[Suggestion]:
    """Die Top-Plätze jeder Rangliste aus einem Lauf über das VOLLE Universum."""
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT r.created_at, s.ticker, s.bucket, s.rank, s.composite, s.region, s.sector
            FROM run_scores s
            JOIN runs r ON r.id = s.run_id
            WHERE s.rank <= ? AND r.universe_size >= ? AND r.created_at >= ?
            ORDER BY r.created_at, s.bucket, s.rank
            """,
            (cutoff, MIN_FULL_UNIVERSE, FULL_UNIVERSE_FROM),
        ).fetchall()
    return [
        Suggestion(
            source="rank",
            ticker=row["ticker"],
            suggested_at=row["created_at"],
            score=float(row["composite"]) * 100,
            bucket=row["bucket"],
            region=row["region"],
            sector=row["sector"],
            rank=int(row["rank"]),
        )
        for row in rows
    ]
