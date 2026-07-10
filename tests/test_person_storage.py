"""person_scores persistence: replace-on-refresh, honest ordering."""
from __future__ import annotations

from equity_scout.evidence.person_storage import (
    load_person_scores,
    person_score_index,
    save_person_scores,
)
from equity_scout.evidence.person_track import PersonScore

NOW = "2026-07-10T12:00:00+00:00"


def _score(person: str, weighted: float | None, n: int = 6, scoreable: bool = True):
    return PersonScore(
        person=person, source="congress", n_calls=n, n_unresolvable=0,
        hit_rate_short=0.5, hit_rate_long=0.6, mean_abnormal_short=0.01,
        mean_abnormal_long=weighted, weighted_score=weighted, scoreable=scoreable,
    )


def test_save_and_load_orders_scoreable_best_first(tmp_path):
    db = str(tmp_path / "p.db")
    save_person_scores(
        db,
        [
            _score("Mid", 0.01),
            _score("Top", 0.05),
            _score("Thin", None, n=2, scoreable=False),
        ],
        now=NOW,
    )
    rows = load_person_scores(db)
    assert [r["person"] for r in rows] == ["Top", "Mid", "Thin"]
    assert rows[0]["computed_at"] == NOW
    assert rows[2]["scoreable"] is False


def test_refresh_replaces_per_person_instead_of_duplicating(tmp_path):
    db = str(tmp_path / "p.db")
    save_person_scores(db, [_score("Jane", 0.01)], now=NOW)
    save_person_scores(db, [_score("Jane", 0.03)], now="2026-07-17T12:00:00+00:00")
    rows = load_person_scores(db)
    assert len(rows) == 1
    assert rows[0]["weighted_score"] == 0.03
    assert rows[0]["computed_at"] == "2026-07-17T12:00:00+00:00"


def test_person_score_index_keys_by_person_and_source(tmp_path):
    db = str(tmp_path / "p.db")
    save_person_scores(db, [_score("Jane", 0.02)], now=NOW)
    index = person_score_index(db)
    assert index[("Jane", "congress")]["weighted_score"] == 0.02
