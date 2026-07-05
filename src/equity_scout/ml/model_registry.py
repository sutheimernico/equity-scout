"""Versioned registry for pickled `EntryModel` artifacts + champion/challenger promotion.

Every trained model is registered as an immutable versioned row (the fitted model pickled into
`artifact`, with its OOS metrics). Exactly one row is the champion. A challenger replaces the
champion ONLY on a strictly better out-of-sample score (honesty invariant #5) — a tie or a worse
score keeps the incumbent, and an un-scored challenger (metric `None`, treated as −inf) never wins.
The very first registered model bootstraps the champion regardless of its metric, because the arena
needs some champion to start from. The champion flip (unset old, set new) happens in one transaction.

Storage follows the repo idiom (raw sqlite3, idempotent init, per-function connections). The pickle
load is guarded: a corrupt or wrong-shaped artifact raises `RegistryError` rather than surfacing a
raw unpickling error to the caller.
"""
from __future__ import annotations

import json
import math
import pickle
import sqlite3

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.ml.entry_model import EntryModel


class RegistryError(RuntimeError):
    """Raised when a stored model artifact cannot be loaded as an `EntryModel`."""


def init_registry_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS entry_models (
                version INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                model_kind TEXT NOT NULL,
                feature_columns TEXT NOT NULL,
                n_train INTEGER NOT NULL,
                metrics_json TEXT NOT NULL,
                is_champion INTEGER NOT NULL DEFAULT 0,
                artifact BLOB NOT NULL
            )"""
        )


def register_challenger(
    db_path: str,
    model: EntryModel,
    *,
    metrics: dict,
    n_train: int,
    now: str,
) -> int:
    """Persist a fitted model as a new challenger version (never a champion by itself — call
    `promote_if_better` to promote it). Returns the assigned version."""
    init_registry_db(db_path)
    artifact = pickle.dumps(model)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO entry_models"
            " (created_at, model_kind, feature_columns, n_train, metrics_json, is_champion, artifact)"
            " VALUES (?, ?, ?, ?, ?, 0, ?)",
            (
                now,
                model.model_kind,
                json.dumps(list(model.feature_columns)),
                int(n_train),
                json.dumps(metrics),
                sqlite3.Binary(artifact),
            ),
        )
        assert cursor.lastrowid is not None  # guaranteed after a successful INSERT
        return int(cursor.lastrowid)


def _load_artifact(blob: bytes) -> EntryModel:
    try:
        model = pickle.loads(blob)
    except Exception as exc:  # noqa: BLE001 — any unpickling failure is a registry error
        raise RegistryError(f"could not unpickle model artifact: {exc}") from exc
    if not isinstance(model, EntryModel):
        raise RegistryError(f"artifact is not an EntryModel (got {type(model).__name__})")
    return model


def _metric(metrics_json: str, key: str) -> float:
    """The comparison metric as a float. A missing/None value — or any non-finite value (NaN/inf,
    which json round-trips) — is −inf so it can never win: a corrupt-metric challenger must not be
    able to displace a legitimate champion (`nan <= x` is False, so NaN must be mapped, not passed)."""
    value = json.loads(metrics_json).get(key)
    if value is None:
        return float("-inf")
    value = float(value)
    return value if math.isfinite(value) else float("-inf")


def champion(db_path: str = DEFAULT_DB_PATH) -> tuple[int, EntryModel, dict] | None:
    """The current champion as (version, EntryModel, metrics), or None if none is promoted yet."""
    init_registry_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT version, artifact, metrics_json FROM entry_models WHERE is_champion = 1"
        ).fetchone()
    if row is None:
        return None
    return int(row[0]), _load_artifact(row[1]), json.loads(row[2])


def promote_if_better(db_path: str, version: int, *, metric_key: str = "auc") -> bool:
    """Promote `version` to champion iff its OOS `metric_key` is STRICTLY greater than the current
    champion's (None → −inf, never wins). The first ever model bootstraps unconditionally. Returns
    True when a promotion happened; idempotent (re-promoting the incumbent is a no-op → False)."""
    init_registry_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cand = conn.execute(
            "SELECT metrics_json FROM entry_models WHERE version = ?", (version,)
        ).fetchone()
        if cand is None:
            raise ValueError(f"unknown model version: {version}")
        champ = conn.execute(
            "SELECT version, metrics_json FROM entry_models WHERE is_champion = 1"
        ).fetchone()
        if champ is not None and int(champ[0]) == version:
            return False  # already the champion → nothing to flip
        if champ is not None and _metric(cand[0], metric_key) <= _metric(champ[1], metric_key):
            return False  # strictly-greater only: a tie or worse keeps the incumbent
        # bootstrap (no champion) or a strictly-better challenger → flip in one transaction
        conn.execute("UPDATE entry_models SET is_champion = 0 WHERE is_champion = 1")
        conn.execute("UPDATE entry_models SET is_champion = 1 WHERE version = ?", (version,))
        return True


def registry_summary(db_path: str = DEFAULT_DB_PATH) -> dict:
    """All registered versions (newest first) with metrics/created_at/champion flag, for the API."""
    init_registry_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT version, created_at, model_kind, n_train, metrics_json, is_champion"
            " FROM entry_models ORDER BY version DESC"
        ).fetchall()
    versions = [
        {
            "version": int(r[0]),
            "created_at": r[1],
            "model_kind": r[2],
            "n_train": int(r[3]),
            "metrics": json.loads(r[4]),
            "is_champion": bool(r[5]),
        }
        for r in rows
    ]
    champion_version = next((v["version"] for v in versions if v["is_champion"]), None)
    return {"versions": versions, "champion_version": champion_version}
