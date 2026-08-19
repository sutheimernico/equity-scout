"""The register of QUALIFIED plateaus — the missing link between measuring and trading (v17).

## Why this file exists

`find_plateaus` has been able to find connected winning regions since 2026-08-17, and nothing
ever read them. No `Strategy` consulted them, no sleeve was built from them: the matrix was a
measuring instrument with no trigger. Nico's brief from 2026-08-17 ("basierend auf gelerntem
Wissen, was nachweislich erfolgreich war, und dann mit Risikoabschätzung entsprechende Hebel")
requires exactly this step, and v17 makes it trader #3.

A plateau does not become tradable by being found. It has to pass, in this order:

1. `find_plateaus` — a connected region, not a lucky cell.
2. **Calendar-block bootstrap** (`matrix/bootstrap.py`) — the pooled t of the Stouffer era was
   inflated by a factor of 1.9 on real data, so a plateau that only qualified under the old
   statistic is not evidence at all.
3. **Robustness re-measurement** — entry at `open[i+1]` instead of the signal close, because a
   same-bar entry can silently harvest the bid-ask bounce that the signal itself selected for.
4. **The hold-out**, opened ONCE.

Only a plateau with all four recorded here may be traded, and every one carries its full
provenance: which signal, which thresholds, which slices, which cost level, which bootstrap
numbers, which hold-out result. When the trader takes a position later, the question "why do we
own this?" has a documented answer instead of a plausible story.

## The hold-out is a consumable

2023-2025 can be opened once. Every opening is registered with its hypothesis BEFORE the result
is known, and a second opening of the same window is refused. Without that discipline, "open the
hold-out, adjust, open again" turns the only clean data left into another search window — the
single most expensive mistake available to this project.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from equity_scout import db

DEFAULT_MATRIX_DB_PATH = "matrix.db"

# Verdict values, in the order a plateau travels through them.
STAGE_FOUND = "found"            # a connected region exists
STAGE_BOOTSTRAPPED = "bootstrapped"  # survived the dependence-aware statistic
STAGE_ROBUST = "robust"          # survived the entry/cost robustness variants
STAGE_QUALIFIED = "qualified"    # survived the hold-out — tradable
STAGE_REJECTED = "rejected"      # died at some stage; kept, because a graveyard is data

STAGES = (STAGE_FOUND, STAGE_BOOTSTRAPPED, STAGE_ROBUST, STAGE_QUALIFIED, STAGE_REJECTED)

# A qualified plateau must clear these. Deliberately stricter than PLATEAU_T (2.0): that one
# gates a single cell under a statistic we now know was optimistic.
MIN_BOOTSTRAP_T = 2.0
MAX_BOOTSTRAP_P = 0.05
MIN_TRADES_QUALIFIED = 200


def init_matrix_db(db_path: str | Path) -> None:
    with db.connect(str(db_path)) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS matrix_plateaus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL,
                stage TEXT NOT NULL,
                side TEXT NOT NULL,
                signal TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                context TEXT NOT NULL,
                cost_bps REAL NOT NULL,
                thresholds TEXT NOT NULL,
                slices TEXT NOT NULL,
                hold_bars TEXT NOT NULL,
                size INTEGER NOT NULL,
                median_net_bp REAL,
                worst_net_bp REAL,
                total_trades INTEGER,
                bootstrap_json TEXT,
                robustness_json TEXT,
                holdout_json TEXT,
                rejected_reason TEXT,
                UNIQUE (fingerprint)
            );

            CREATE TABLE IF NOT EXISTS holdout_openings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                window_start TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                fingerprints TEXT NOT NULL,
                result_json TEXT,
                UNIQUE (window_start)
            );
            """
        )


def fingerprint(plateau: dict, *, side: str = "long") -> str:
    """Stable identity of a plateau across runs.

    Built from the region's DEFINING axes, not from its statistics — the same rule re-measured
    on more data is the same rule, and must not slip into the register a second time under a new
    identity. That is how a "new finding" gets manufactured by accident.
    """
    parts = [
        side, plateau["signal"], str(plateau["asset_class"]),
        str(plateau.get("context", "none")), f"{float(plateau['cost_bps']):.1f}",
        ",".join(str(t) for t in plateau["thresholds"]),
        ",".join(str(s) for s in plateau["slices"]),
        ",".join(str(h) for h in plateau["hold_bars"]),
    ]
    return "|".join(parts)


@dataclass(frozen=True)
class QualifiedPlateau:
    """A plateau cleared for trading, with everything needed to act on it and to audit it."""

    fingerprint: str
    side: str
    signal: str
    asset_class: str
    context: str
    cost_bps: float
    thresholds: list
    slices: list
    hold_bars: list
    median_net_bp: float
    bootstrap_t: float
    bootstrap_p: float
    std_error_bp: float
    total_trades: int

    @property
    def risk_weight(self) -> float:
        """Position size factor in [0, 1] from the bootstrap's own uncertainty.

        Nico's brief asks for "Risikoabschätzung entsprechende Hebel". The honest reading is the
        inverse: size DOWN when the estimate is uncertain, never up. The ratio
        mean / standard-error is exactly the bootstrap t, so a plateau at t = 2 (the floor) gets
        a quarter weight and one at t = 8 gets full weight. Capped at 1.0 — this factor can
        never create leverage, only reduce exposure.
        """
        if self.std_error_bp <= 0:
            return 0.0
        return max(0.0, min(1.0, self.bootstrap_t / 8.0))


def record_plateau(
    db_path: str | Path,
    plateau: dict,
    *,
    now: str,
    stage: str,
    side: str = "long",
    bootstrap: dict | None = None,
    robustness: dict | None = None,
    holdout: dict | None = None,
    rejected_reason: str | None = None,
) -> str:
    """Insert or advance one plateau; returns its fingerprint.

    An existing row is UPDATED rather than duplicated, so a plateau's journey through the stages
    stays one auditable record instead of four competing ones.
    """
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    key = fingerprint(plateau, side=side)
    init_matrix_db(db_path)
    with db.connect(str(db_path)) as con:
        con.execute(
            """
            INSERT INTO matrix_plateaus
                (fingerprint, created_at, stage, side, signal, asset_class, context, cost_bps,
                 thresholds, slices, hold_bars, size, median_net_bp, worst_net_bp,
                 total_trades, bootstrap_json, robustness_json, holdout_json, rejected_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (fingerprint) DO UPDATE SET
                stage = excluded.stage,
                bootstrap_json = COALESCE(excluded.bootstrap_json, bootstrap_json),
                robustness_json = COALESCE(excluded.robustness_json, robustness_json),
                holdout_json = COALESCE(excluded.holdout_json, holdout_json),
                rejected_reason = excluded.rejected_reason
            """,
            (
                key, now, stage, side, plateau["signal"], str(plateau["asset_class"]),
                str(plateau.get("context", "none")), float(plateau["cost_bps"]),
                json.dumps(plateau["thresholds"]), json.dumps(plateau["slices"]),
                json.dumps(plateau["hold_bars"]), int(plateau["size"]),
                plateau.get("median_net_bp"), plateau.get("worst_net_bp"),
                plateau.get("total_trades"),
                json.dumps(bootstrap) if bootstrap else None,
                json.dumps(robustness) if robustness else None,
                json.dumps(holdout) if holdout else None,
                rejected_reason,
            ),
        )
    return key


def bootstrap_verdict(result: dict, *, min_trades: int = MIN_TRADES_QUALIFIED) -> tuple[bool, str]:
    """(passes, reason) for one bootstrap result dict (see bootstrap.BootstrapResult.as_dict).

    A None t is a REFUSAL, not a pass and not a rejection: too few calendar blocks means the
    sample cannot answer the question. Treating it as either would be a lie in one direction.
    """
    if result.get("t") is None or result.get("p_value") is None:
        return False, "nicht messbar (zu wenige Kalenderblöcke)"
    if (result.get("n_trades") or 0) < min_trades:
        return False, f"nur {result.get('n_trades')} Trades (Schwelle {min_trades})"
    if (result.get("mean_net_bp") or 0.0) <= 0:
        return False, "nach Kosten nicht positiv"
    if result["t"] < MIN_BOOTSTRAP_T:
        return False, f"Bootstrap-t {result['t']:.2f} unter {MIN_BOOTSTRAP_T}"
    if result["p_value"] > MAX_BOOTSTRAP_P:
        return False, f"p {result['p_value']:.3f} über {MAX_BOOTSTRAP_P}"
    if (result.get("ci_low_bp") or 0.0) <= 0:
        return False, "95-%-Intervall enthält die Null"
    return True, "bestanden"


def load_qualified(db_path: str | Path) -> list[QualifiedPlateau]:
    """Every tradable plateau. An empty list is the normal, honest state until one qualifies."""
    if not Path(db_path).exists():
        return []
    init_matrix_db(db_path)
    with db.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM matrix_plateaus WHERE stage = ? ORDER BY median_net_bp DESC",
            (STAGE_QUALIFIED,),
        ).fetchall()
    out = []
    for row in rows:
        boot = json.loads(row["bootstrap_json"] or "{}")
        if boot.get("t") is None or boot.get("std_error_bp") is None:
            # A qualified row without its statistics cannot be sized, so it must not trade.
            continue
        out.append(QualifiedPlateau(
            fingerprint=row["fingerprint"], side=row["side"], signal=row["signal"],
            asset_class=row["asset_class"], context=row["context"],
            cost_bps=row["cost_bps"], thresholds=json.loads(row["thresholds"]),
            slices=json.loads(row["slices"]), hold_bars=json.loads(row["hold_bars"]),
            median_net_bp=row["median_net_bp"] or 0.0,
            bootstrap_t=float(boot["t"]), bootstrap_p=float(boot.get("p_value") or 1.0),
            std_error_bp=float(boot["std_error_bp"]), total_trades=row["total_trades"] or 0,
        ))
    return out


def load_all(db_path: str | Path, *, stage: str | None = None) -> list[dict]:
    """Everything in the register, rejections included — the graveyard is evidence too."""
    if not Path(db_path).exists():
        return []
    init_matrix_db(db_path)
    where, params = ("WHERE stage = ?", (stage,)) if stage else ("", ())
    with db.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT * FROM matrix_plateaus {where} ORDER BY id DESC", params
        ).fetchall()
    return [dict(r) for r in rows]


# --- the hold-out, as a consumable resource ------------------------------------------------

def holdout_is_open(db_path: str | Path, window_start: str) -> bool:
    """True while this hold-out window has never been opened."""
    if not Path(db_path).exists():
        return True
    init_matrix_db(db_path)
    with db.connect(str(db_path)) as con:
        row = con.execute(
            "SELECT 1 FROM holdout_openings WHERE window_start = ?", (window_start,)
        ).fetchone()
    return row is None


def register_holdout_opening(
    db_path: str | Path,
    *,
    window_start: str,
    now: str,
    hypothesis: str,
    fingerprints: list[str],
) -> None:
    """Claim the hold-out BEFORE seeing the result. Raises if it was already spent.

    The hypothesis and the candidate list are written first, on purpose: a hypothesis recorded
    after the fact is not a hypothesis. The refusal on a second attempt is the whole point —
    it is what keeps the window from decaying into a second search space.
    """
    init_matrix_db(db_path)
    if not holdout_is_open(db_path, window_start):
        raise RuntimeError(
            f"Hold-out ab {window_start} wurde bereits geöffnet — es ist verbraucht. "
            "Ein zweites Öffnen würde aus dem letzten unberührten Datensatz ein "
            "weiteres Suchfenster machen."
        )
    with db.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO holdout_openings (window_start, opened_at, hypothesis, fingerprints) "
            "VALUES (?, ?, ?, ?)",
            (window_start, now, hypothesis, json.dumps(fingerprints)),
        )


def record_holdout_result(db_path: str | Path, *, window_start: str, result: dict) -> None:
    init_matrix_db(db_path)
    with db.connect(str(db_path)) as con:
        con.execute(
            "UPDATE holdout_openings SET result_json = ? WHERE window_start = ?",
            (json.dumps(result), window_start),
        )


def holdout_log(db_path: str | Path) -> list[dict]:
    if not Path(db_path).exists():
        return []
    init_matrix_db(db_path)
    with db.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(
            "SELECT * FROM holdout_openings ORDER BY id DESC").fetchall()]
