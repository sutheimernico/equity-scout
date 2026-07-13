"""Versioned registry for pickled `EntryModel` artifacts + champion/challenger promotion.

Every trained model is registered as an immutable versioned row (the fitted model pickled into
`artifact`, with its OOS metrics). Exactly one row is the champion. Promotion (`promote_if_better`)
is gated on two things (F2, since nightly retrains are nightly trials and noise alone must not be
able to swap the champion): (1) baseline quality — the metric clears the no-edge band (see
`_no_edge`) and rests on at least `MIN_OOS_N` out-of-sample rows; a model that fails this is never
promoted, not even as the FIRST champion — an empty arena has no champion rather than a fake one.
(2) once a champion exists, a challenger must beat it by at least `MIN_AUC_DELTA`; a tie or a
smaller improvement keeps the incumbent. An un-scored challenger (metric `None`, treated as −inf)
never wins. The champion flip (unset old, set new) happens in one transaction.

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

# Minimum OOS AUC improvement a challenger must show over the incumbent champion to be promoted.
# Nightly retrains are nightly trials against the same OOS metric; without a floor, noise alone
# would eventually swap the champion (F2).
MIN_AUC_DELTA = 0.01

# Minimum OOS row count for a promotion decision to be trustworthy. Below this, an AUC estimate is
# too noisy to act on — the model registers as a challenger but never becomes champion.
MIN_OOS_N = 200

# |auc - 0.5| below this band = no demonstrated ranking edge (a coin flip). `_no_edge` below is the
# single source of truth: it blocks promotion here AND is imported by the CLI (run_train_entry.py)
# to explain a non-promotion honestly instead of silently going quiet.
NO_EDGE_BAND = 0.05


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
                artifact BLOB NOT NULL,
                family TEXT NOT NULL DEFAULT 'entry'
            )"""
        )
        # Pre-family DBs (v5 and earlier): add the column in place; existing rows are the long
        # entry model by construction, which the DEFAULT covers.
        try:
            conn.execute("ALTER TABLE entry_models ADD COLUMN family TEXT NOT NULL DEFAULT 'entry'")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Learning-curve backbone (plan v6 P4): every successful promotion appends one row, so
        # "when did the champion change, and was each change an actual improvement?" is a query.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS champion_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                family TEXT NOT NULL,
                version INTEGER NOT NULL,
                prior_version INTEGER,
                promoted_at TEXT NOT NULL,
                auc REAL,
                n_oos INTEGER
            )"""
        )


def register_challenger(
    db_path: str,
    model: EntryModel,
    *,
    metrics: dict,
    n_train: int,
    now: str,
    family: str = "entry",
) -> int:
    """Persist a fitted model as a new challenger version (never a champion by itself — call
    `promote_if_better` to promote it). `family` partitions the registry ("entry" long model vs
    "entry_short") — champions and promotion comparisons never cross families, so the long and
    short bots each keep their own honest accounting. Returns the assigned version."""
    init_registry_db(db_path)
    artifact = pickle.dumps(model)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO entry_models"
            " (created_at, model_kind, feature_columns, n_train, metrics_json, is_champion,"
            " artifact, family)"
            " VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (
                now,
                model.model_kind,
                json.dumps(list(model.feature_columns)),
                int(n_train),
                json.dumps(metrics),
                sqlite3.Binary(artifact),
                family,
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


def _raw_metric(metrics_json: str, key: str) -> float | None:
    """The metric's raw value, or None if it is missing or non-finite (NaN/inf, which json
    round-trips as literals). Kept distinct from `_metric` because some checks (the no-edge gate)
    must tell "no value at all" apart from "a real value that happens to map to −inf"."""
    value = json.loads(metrics_json).get(key)
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _metric(metrics_json: str, key: str) -> float:
    """The comparison metric as a float. A missing/None value — or any non-finite value (NaN/inf,
    which json round-trips) — is −inf so it can never win: a corrupt-metric challenger must not be
    able to displace a legitimate champion (`nan <= x` is False, so NaN must be mapped, not passed)."""
    raw = _raw_metric(metrics_json, key)
    return raw if raw is not None else float("-inf")


def _no_edge(auc: float | None) -> bool:
    """No demonstrated ranking edge: AUC undefined/non-finite, or within a coin-flip band of 0.5.
    Enforced here (not just printed by the CLI) so a null result can never become champion."""
    return auc is None or abs(auc - 0.5) < NO_EDGE_BAND


def _n_oos(metrics_json: str) -> int:
    """OOS row count backing the metric, or 0 if absent — an unreported count cannot be assumed
    adequate."""
    value = json.loads(metrics_json).get("n_oos")
    return int(value) if value is not None else 0


def entry_champion(
    db_path: str = DEFAULT_DB_PATH, *, family: str = "entry"
) -> tuple[int, EntryModel, dict] | None:
    """The current champion of `family` as (version, EntryModel, metrics), or None if none is
    promoted yet.

    Named `entry_champion` (not `champion`) to stay distinct from `ml.ledger.champion`, which
    returns a different type (the research-loop config record) — importing both must never collide.
    """
    init_registry_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT version, artifact, metrics_json FROM entry_models"
            " WHERE is_champion = 1 AND family = ?",
            (family,),
        ).fetchone()
    if row is None:
        return None
    return int(row[0]), _load_artifact(row[1]), json.loads(row[2])


def promote_if_better(
    db_path: str, version: int, *, metric_key: str = "auc", now: str = ""
) -> bool:
    """Promote `version` to champion iff it clears the promotion gate (F2):

    1. Baseline quality — its OOS `metric_key` is not a no-edge result (`_no_edge`) and rests on at
       least `MIN_OOS_N` OOS rows. Applies even to the very first model: an empty arena has no
       champion rather than a fake one bootstrapped off an undemonstrated edge.
    2. If a champion already exists, `version` must beat it by at least `MIN_AUC_DELTA` — nightly
       retrains are nightly trials, so noise alone (a tie or a marginally-better score) must not be
       able to swap the champion.

    Promotion is scoped to the candidate's FAMILY: the long and short registries never compare
    against each other's champions. Returns True iff a promotion happened; idempotent
    (re-promoting the incumbent is a no-op → False)."""
    init_registry_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cand = conn.execute(
            "SELECT metrics_json, family FROM entry_models WHERE version = ?", (version,)
        ).fetchone()
        if cand is None:
            raise ValueError(f"unknown model version: {version}")
        family = cand[1]
        champ = conn.execute(
            "SELECT version, metrics_json FROM entry_models WHERE is_champion = 1 AND family = ?",
            (family,),
        ).fetchone()
        if champ is not None and int(champ[0]) == version:
            return False  # already the champion → nothing to flip

        if _n_oos(cand[0]) < MIN_OOS_N or _no_edge(_raw_metric(cand[0], metric_key)):
            return False  # fails baseline quality → never becomes champion, first or not
        if champ is not None:
            delta = _metric(cand[0], metric_key) - _metric(champ[1], metric_key)
            if delta < MIN_AUC_DELTA:
                return False  # improvement over the incumbent is below the noise-guard threshold

        # bootstrap (no champion) or a challenger clearing both gates → flip in one transaction
        conn.execute(
            "UPDATE entry_models SET is_champion = 0 WHERE is_champion = 1 AND family = ?",
            (family,),
        )
        conn.execute("UPDATE entry_models SET is_champion = 1 WHERE version = ?", (version,))
        conn.execute(
            "INSERT INTO champion_history"
            " (family, version, prior_version, promoted_at, auc, n_oos) VALUES (?, ?, ?, ?, ?, ?)",
            (
                family, version,
                int(champ[0]) if champ is not None else None,
                now,
                _raw_metric(cand[0], metric_key),
                _n_oos(cand[0]),
            ),
        )
        return True


def load_champion_history(db_path: str = DEFAULT_DB_PATH, *, family: str | None = None) -> list[dict]:
    """Every promotion event (oldest first): when the champion changed, from which version, and
    the OOS quality it demonstrated at that moment — the honest x-axis of the learning curve."""
    init_registry_db(db_path)
    filt = "" if family is None else " WHERE family = ?"
    args: tuple = () if family is None else (family,)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT family, version, prior_version, promoted_at, auc, n_oos"
            f" FROM champion_history{filt} ORDER BY id ASC",
            args,
        ).fetchall()
    return [
        {
            "family": r[0],
            "version": int(r[1]),
            "prior_version": int(r[2]) if r[2] is not None else None,
            "promoted_at": r[3],
            "auc": r[4],
            "n_oos": int(r[5]) if r[5] is not None else None,
        }
        for r in rows
    ]


def registry_summary(db_path: str = DEFAULT_DB_PATH) -> dict:
    """All registered versions (newest first) with metrics/created_at/champion flag, for the API.
    `champion_version` stays the LONG entry champion (pre-family API contract); `champions` maps
    every family to its champion version."""
    init_registry_db(db_path)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT version, created_at, model_kind, n_train, metrics_json, is_champion, family"
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
            "family": r[6],
        }
        for r in rows
    ]
    champions = {v["family"]: v["version"] for v in versions if v["is_champion"]}
    return {
        "versions": versions,
        "champion_version": champions.get("entry"),
        "champions": champions,
    }
