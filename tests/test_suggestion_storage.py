"""Was als Vorschlag ZÄHLT — und was der Bericht daraus macht (Nachtschicht 2026-08-27).

Die Auswahl ist der heikle Teil: jede Filterregel, die hier zu großzügig oder zu wählerisch
ist, verschiebt das Urteil, ohne dass es jemand an der Zahl sehen könnte.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_suggestion_review import build_report  # noqa: E402

from equity_scout.suggestion_storage import (  # noqa: E402
    collect_pitch_suggestions,
    collect_rank_suggestions,
    load_latest_review,
    save_review,
)


def _db(tmp_path: Path) -> str:
    """Eine Mini-DB mit genau den Tabellen, die die Sammler lesen."""
    path = str(tmp_path / "test.db")
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            CREATE TABLE pitches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                ticker TEXT NOT NULL, price REAL NOT NULL, composite REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'open', verdict TEXT
            );
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                universe_size INTEGER NOT NULL
            );
            CREATE TABLE run_scores (
                run_id INTEGER NOT NULL, bucket TEXT NOT NULL, rank INTEGER NOT NULL,
                ticker TEXT NOT NULL, composite REAL NOT NULL, region TEXT NOT NULL,
                sector TEXT NOT NULL
            );
            """
        )
    return path


def _add_run(path: str, *, created_at: str, universe_size: int, picks: list[tuple[int, str]]) -> None:
    with sqlite3.connect(path) as con:
        cur = con.execute(
            "INSERT INTO runs (created_at, universe_size) VALUES (?, ?)",
            (created_at, universe_size),
        )
        run_id = cur.lastrowid
        for rank, ticker in picks:
            con.execute(
                "INSERT INTO run_scores (run_id, bucket, rank, ticker, composite, region, sector)"
                " VALUES (?, 'balanced', ?, ?, 0.8, 'US', 'Energy')",
                (run_id, rank, ticker),
            )


def test_every_pitch_counts_including_the_expired_and_the_red_ones(tmp_path):
    """Nur die grünen zu messen wäre die Auswahl der Ergebnisse, die man sehen will."""
    path = _db(tmp_path)
    with sqlite3.connect(path) as con:
        con.executemany(
            "INSERT INTO pitches (created_at, ticker, price, composite, status, verdict)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("2026-07-05T16:00:00+00:00", "AAA", 10.0, 0.7, "expired", "red"),
                ("2026-07-06T16:00:00+00:00", "BBB", 20.0, 0.6, "buy", "green"),
                ("2026-07-07T16:00:00+00:00", "CCC", 30.0, 0.5, "open", None),
            ],
        )
    collected = collect_pitch_suggestions(path)
    assert [s.ticker for s in collected] == ["AAA", "BBB", "CCC"]
    assert all(s.source == "pitch" for s in collected)


def test_the_pitch_price_is_carried_as_quoted_never_as_entry(tmp_path):
    path = _db(tmp_path)
    with sqlite3.connect(path) as con:
        con.execute(
            "INSERT INTO pitches (created_at, ticker, price, composite) VALUES (?, ?, ?, ?)",
            ("2026-07-05T16:00:00+00:00", "AAA", 42.0, 0.7),
        )
    assert collect_pitch_suggestions(path)[0].quoted_price == 42.0


def test_the_score_is_stored_on_the_same_0_to_100_scale_as_the_surfaces(tmp_path):
    path = _db(tmp_path)
    with sqlite3.connect(path) as con:
        con.execute(
            "INSERT INTO pitches (created_at, ticker, price, composite) VALUES (?, ?, ?, ?)",
            ("2026-07-05T16:00:00+00:00", "AAA", 42.0, 0.685),
        )
    assert collect_pitch_suggestions(path)[0].score == 68.5


def test_runs_on_a_partial_universe_are_excluded(tmp_path):
    """Die Juni-Runs liefen auf 42 und 531 Titeln — das ist nicht dieselbe Maschine."""
    path = _db(tmp_path)
    _add_run(path, created_at="2026-06-25T00:00:00+00:00", universe_size=531, picks=[(1, "OLD")])
    _add_run(path, created_at="2026-07-14T21:00:00+00:00", universe_size=7499, picks=[(1, "NEW")])
    assert [s.ticker for s in collect_rank_suggestions(path)] == ["NEW"]


def test_a_full_universe_run_before_the_cutover_date_is_still_excluded(tmp_path):
    """Beide Bedingungen müssen greifen — sonst schlüpft ein Grenzfall durch."""
    path = _db(tmp_path)
    _add_run(path, created_at="2026-07-01T00:00:00+00:00", universe_size=7499, picks=[(1, "EARLY")])
    assert collect_rank_suggestions(path) == []


def test_only_the_top_ranks_count_as_a_suggestion(tmp_path):
    """Platz 40 einer Rangliste hat Nico nie gesehen."""
    path = _db(tmp_path)
    _add_run(
        path, created_at="2026-07-14T21:00:00+00:00", universe_size=7499,
        picks=[(1, "TOP"), (5, "EDGE"), (6, "OUT"), (40, "DEEP")],
    )
    assert {s.ticker for s in collect_rank_suggestions(path)} == {"TOP", "EDGE"}


def test_the_rank_cutoff_is_a_parameter_not_a_hidden_constant(tmp_path):
    path = _db(tmp_path)
    _add_run(
        path, created_at="2026-07-14T21:00:00+00:00", universe_size=7499,
        picks=[(1, "A"), (2, "B"), (3, "C")],
    )
    assert len(collect_rank_suggestions(path, cutoff=2)) == 2


def test_a_review_round_trips_and_the_latest_one_wins(tmp_path):
    path = str(tmp_path / "r.db")
    save_review(path, "2026-08-26T00:00:00+00:00", {"n_measured": 1})
    save_review(path, "2026-08-27T00:00:00+00:00", {"n_measured": 2})
    latest = load_latest_review(path)
    assert latest is not None
    assert latest["n_measured"] == 2
    assert latest["computed_at"] == "2026-08-27T00:00:00+00:00"


def test_a_missing_database_is_an_absence_not_a_crash(tmp_path):
    assert load_latest_review(str(tmp_path / "nope.db")) is None


def test_a_database_without_the_table_is_also_just_an_absence(tmp_path):
    path = str(tmp_path / "empty.db")
    sqlite3.connect(path).close()
    assert load_latest_review(path) is None


# --- Der Bericht ---------------------------------------------------------------------------

def _flat_series(days: int, start_day: int = 1) -> list[tuple[str, float]]:
    return [(f"2026-07-{start_day + i:02d}", 100.0) for i in range(days)]


def _rising_series(days: int) -> list[tuple[str, float]]:
    return [(f"2026-07-{1 + i:02d}", 100.0 + i) for i in range(days)]


def test_a_ticker_without_prices_is_reported_as_a_gap_not_dropped_silently():
    from equity_scout.suggestion_review import Suggestion

    suggestions = [
        Suggestion(source="pitch", ticker="GHOST", suggested_at="2026-07-01T16:00:00+00:00"),
    ]
    report = build_report(suggestions, {}, now="2026-08-27T00:00:00+00:00")
    assert report["missing_prices"] == ["GHOST"]
    assert report["n_measured"] == 0


def test_the_report_separates_pitches_from_ranks():
    """Ein Pitch ist eine Aufforderung, ein Rang eine Sortierung — nie derselbe Topf."""
    from equity_scout.suggestion_review import Suggestion

    series = {"AAA": _rising_series(28), "^GSPC": _flat_series(28)}
    suggestions = [
        Suggestion(source="pitch", ticker="AAA", suggested_at="2026-07-01T16:00:00+00:00"),
        Suggestion(source="rank", ticker="AAA", suggested_at="2026-07-01T16:00:00+00:00", rank=1),
    ]
    report = build_report(suggestions, series, now="2026-08-27T00:00:00+00:00")
    by_source = {(s["source"], s["horizon_days"]): s for s in report["summaries"]}
    assert by_source[("pitch", 5)]["n"] == 1
    assert by_source[("rank", 5)]["n"] == 1
    # Der steigende Titel gegen den flachen Index: beide Seiten sehen denselben Exzess.
    assert (by_source[("pitch", 5)]["mean_excess_pct"] or 0) > 0


def test_every_horizon_gets_its_own_row_even_when_empty():
    report = build_report([], {}, now="2026-08-27T00:00:00+00:00")
    assert len(report["summaries"]) == 2 * len(report["horizons"])
    assert all(s["n"] == 0 for s in report["summaries"])


def test_the_report_carries_the_disclaimer():
    report = build_report([], {}, now="2026-08-27T00:00:00+00:00")
    assert "keine anlageberatung" in report["disclaimer"].lower()


# --- Ein gedrosselter Abruf ist ein Fehlschlag, kein Messergebnis ------------------------------

def test_coverage_counts_only_tickers_that_really_have_a_series():
    from run_suggestion_review import ticker_coverage

    assert ticker_coverage(["A", "B", "C", "D"], {"A": [("2026-07-01", 1.0)], "B": []}) == 0.25


def test_coverage_of_an_empty_ticker_list_is_zero_not_one():
    """Eine leere Menge ist nicht „vollständig abgedeckt" — das würde die Schwelle aushebeln."""
    from run_suggestion_review import ticker_coverage

    assert ticker_coverage([], {}) == 0.0


def test_a_throttled_run_falls_below_the_threshold():
    """Der reale Lauf vom 2026-08-27 00:05 hatte 0 von 37 Reihen und schrieb trotzdem."""
    from run_suggestion_review import MIN_COVERAGE, ticker_coverage

    assert ticker_coverage([f"T{i}" for i in range(37)], {}) < MIN_COVERAGE
