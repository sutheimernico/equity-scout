"""Learning-curve snapshot tests: idempotent daily upsert, chronological load, honest NULLs."""
from __future__ import annotations

from equity_scout.ml.learning_curve import load_daily_curve, save_snapshot


def test_load_daily_curve_empty_returns_empty_list_not_a_crash(tmp_path):
    db = str(tmp_path / "curve.db")
    assert load_daily_curve(db) == []


def test_save_snapshot_round_trips(tmp_path):
    db = str(tmp_path / "curve.db")
    save_snapshot(
        db, snapshot_date="2026-07-15", created_at="2026-07-15T02:30:00+00:00",
        n_train=120, n_resolved=40, hit_rate=0.55, rank_ic=0.12,
    )
    curve = load_daily_curve(db)
    assert len(curve) == 1
    assert curve[0] == {
        "snapshot_date": "2026-07-15",
        "created_at": "2026-07-15T02:30:00+00:00",
        "n_train": 120,
        "n_resolved": 40,
        "hit_rate": 0.55,
        "rank_ic": 0.12,
    }


def test_save_snapshot_upserts_idempotent_per_day(tmp_path):
    """A second write for the SAME snapshot_date overwrites, never duplicates."""
    db = str(tmp_path / "curve.db")
    save_snapshot(
        db, snapshot_date="2026-07-15", created_at="2026-07-15T02:30:00+00:00",
        n_train=100, n_resolved=10, hit_rate=0.5, rank_ic=0.05,
    )
    save_snapshot(
        db, snapshot_date="2026-07-15", created_at="2026-07-15T03:00:00+00:00",
        n_train=100, n_resolved=15, hit_rate=0.6, rank_ic=0.10,
    )
    curve = load_daily_curve(db)
    assert len(curve) == 1  # overwritten, not appended
    assert curve[0]["n_resolved"] == 15
    assert curve[0]["hit_rate"] == 0.6
    assert curve[0]["created_at"] == "2026-07-15T03:00:00+00:00"


def test_save_snapshot_persists_honest_none_never_a_fake_zero(tmp_path):
    """When a metric cannot be determined (no champion yet, nothing resolved), the row stores
    NULL — not a fabricated 0, which would misrepresent an honest gap as a real reading."""
    db = str(tmp_path / "curve.db")
    save_snapshot(
        db, snapshot_date="2026-07-15", created_at="2026-07-15T02:30:00+00:00",
        n_train=None, n_resolved=0, hit_rate=None, rank_ic=None,
    )
    curve = load_daily_curve(db)
    assert curve[0]["n_train"] is None
    assert curve[0]["n_resolved"] == 0  # a real, honest zero count is not the same as "unknown"
    assert curve[0]["hit_rate"] is None
    assert curve[0]["rank_ic"] is None


def test_load_daily_curve_is_chronological(tmp_path):
    db = str(tmp_path / "curve.db")
    save_snapshot(
        db, snapshot_date="2026-07-16", created_at="2026-07-16T02:30:00+00:00",
        n_train=130, n_resolved=41, hit_rate=0.56, rank_ic=0.13,
    )
    save_snapshot(
        db, snapshot_date="2026-07-14", created_at="2026-07-14T02:30:00+00:00",
        n_train=110, n_resolved=38, hit_rate=0.52, rank_ic=0.09,
    )
    save_snapshot(
        db, snapshot_date="2026-07-15", created_at="2026-07-15T02:30:00+00:00",
        n_train=120, n_resolved=40, hit_rate=0.55, rank_ic=0.12,
    )
    curve = load_daily_curve(db)
    assert [p["snapshot_date"] for p in curve] == ["2026-07-14", "2026-07-15", "2026-07-16"]
