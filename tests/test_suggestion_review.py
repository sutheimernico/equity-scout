""""Hätten die Vorschläge getragen?" (Nachtschicht 2026-08-27).

Die Tests zielen auf die Stellen, an denen die Messung sich selbst schönrechnen könnte:
der Einstiegskurs, die überlappenden Fenster, der fremdwährige Benchmark und das noch
nicht abgelaufene Fenster. Jede dieser vier Abkürzungen würde eine bessere Zahl liefern.
"""
from __future__ import annotations

import pytest

from equity_scout.suggestion_review import (
    Suggestion,
    benchmark_for,
    first_tradable_close,
    independent_outcomes,
    measure,
    sector_concentration,
    summarise,
    verdict_line,
)


def _series(start_day: int, closes: list[float], month: str = "07") -> list[tuple[str, float]]:
    """Tagesreihe ab 2026-<month>-<start_day>, ein Bar pro Kalendertag."""
    return [
        (f"2026-{month}-{start_day + i:02d}", close) for i, close in enumerate(closes)
    ]


def _entry_series(entry: float, later: float, bars: int = 25) -> list[tuple[str, float]]:
    """Reihe, in der der EINSTIEG (Bar 2, der erste kaufbare) `entry` kostet.

    Bar 1 trägt bewusst einen ganz anderen Kurs: läge der Einstieg dort, fiele es hier auf,
    statt die Rendite still um die Bewegung des Vorschlagstags zu verfälschen.
    """
    return _series(1, [entry * 9.99, entry] + [later] * bars)


def _suggestion(**kwargs) -> Suggestion:
    base: dict[str, object] = {
        "source": "rank",
        "ticker": "TEST",
        "suggested_at": "2026-07-01T16:00:00+00:00",
        "region": "US",
    }
    base.update(kwargs)
    return Suggestion(**base)  # type: ignore[arg-type]


# --- Einstiegskurs: nie der Tag des Vorschlags ---------------------------------------------

def test_entry_is_the_next_close_never_the_suggestion_day():
    """Ein Vorschlag um 16:00 kann den Schluss desselben Tages nicht mehr kaufen."""
    series = _series(1, [100.0, 110.0, 120.0])
    found = first_tradable_close(series, "2026-07-01T16:00:00+00:00")
    assert found == (1, "2026-07-02", 110.0)


def test_a_morning_suggestion_also_waits_for_the_next_close():
    """03:30 UTC bezieht sich auf den Schluss des Vortags — auch der ist nicht mehr kaufbar."""
    series = _series(1, [100.0, 110.0, 120.0])
    assert first_tradable_close(series, "2026-07-02T03:30:00+00:00") == (2, "2026-07-03", 120.0)


def test_no_bar_after_the_suggestion_is_not_measurable():
    assert first_tradable_close(_series(1, [100.0]), "2026-07-05T16:00:00+00:00") is None


def test_the_quoted_price_never_becomes_the_entry_price():
    """Der Pitch nannte 100, kaufbar war erst 110 — die Messung nimmt 110."""
    series = _entry_series(110.0, 110.0)
    outcome = measure(_suggestion(quoted_price=100.0), series, horizon_days=5)
    assert outcome is not None
    assert outcome.entry_price == 110.0
    assert outcome.suggestion.quoted_price == 100.0
    assert outcome.return_pct == 0.0  # und nicht die +10 %, die der Anzeigekurs geschenkt hätte


# --- Benchmark: lieber keiner als ein fremdwähriger -----------------------------------------

def test_suffix_beats_region_for_the_benchmark():
    """ITC.NS ist Indien, auch wenn eine Regionsspalte etwas anderes behauptet."""
    assert benchmark_for("ITC.NS", region="US") == "^NSEI"
    assert benchmark_for("9064.T") == "^N225"


def test_a_plain_symbol_uses_the_us_index():
    assert benchmark_for("MU") == "^GSPC"
    assert benchmark_for("MU", region="US") == "^GSPC"


def test_an_unknown_venue_gets_no_benchmark_rather_than_a_wrong_one():
    """Ein unbekanntes Suffix bekommt NICHT den S&P — das würde Wechselkurse messen."""
    assert benchmark_for("FOO.XYZ") is None
    assert benchmark_for("FOO.XYZ", region="US") is None


def test_a_non_us_region_without_suffix_gets_no_benchmark():
    assert benchmark_for("SOMETHING", region="JP") is None


def test_excess_is_none_without_a_benchmark_series_and_the_return_survives():
    series = _entry_series(100.0, 120.0)
    outcome = measure(_suggestion(ticker="FOO.XYZ"), series, horizon_days=5)
    assert outcome is not None
    assert outcome.excess_pct is None
    assert outcome.benchmark_ticker is None
    assert outcome.return_pct == pytest.approx(0.2)


def test_the_benchmark_is_measured_over_the_same_calendar_window():
    """Der Index hat andere Feiertage — verglichen wird das Datumsfenster, nicht die Bar-Zahl."""
    series = _series(1, [100.0, 100.0, 105.0, 110.0, 110.0, 110.0, 110.0])
    # Index ohne Bar am 03.07., dafür einen am 04.07.: der Fensterrand muss trotzdem greifen.
    bench = [("2026-07-01", 50.0), ("2026-07-02", 50.0), ("2026-07-04", 51.0),
             ("2026-07-07", 52.5)]
    outcome = measure(_suggestion(), series, horizon_days=5, benchmark_series=bench)
    assert outcome is not None
    assert outcome.entry_date == "2026-07-02" and outcome.exit_date == "2026-07-07"
    # Titel 100 -> 110 = +10 %, Index 50 -> 52,5 = +5 %, Exzess 5 pp.
    assert round(outcome.return_pct, 6) == 0.1
    assert round(outcome.benchmark_return_pct or 0.0, 6) == 0.05
    assert round(outcome.excess_pct or 0.0, 6) == 0.05


# --- Fenster, die noch laufen, sind kein Ergebnis -------------------------------------------

def test_a_window_that_has_not_run_out_is_not_counted():
    """Zwei Tage nach dem Vorschlag ist ein 60-Tage-Horizont kein Ergebnis."""
    series = _series(1, [100.0, 110.0, 120.0])
    assert measure(_suggestion(), series, horizon_days=60) is None


def test_a_nearly_complete_window_still_counts_and_says_how_far_it_got():
    """18 von 20 Bars sind eine Messung, aber die Bar-Zahl bleibt sichtbar."""
    series = _series(1, [100.0] + [105.0] * 19)
    outcome = measure(_suggestion(), series, horizon_days=20)
    assert outcome is not None
    assert outcome.bars_available == 18
    assert outcome.horizon_days == 20  # der ANGEFRAGTE Horizont, nicht der erreichte


# --- Überlappende Fenster sind keine unabhängigen Beobachtungen -----------------------------

def test_overlapping_windows_of_the_same_ticker_collapse_to_one():
    """Derselbe Titel in drei Runs derselben Woche ist EINE Beobachtung, nicht drei."""
    series = _series(1, [100.0] + [110.0] * 40)
    outcomes = [
        measure(_suggestion(suggested_at=f"2026-07-0{d}T16:00:00+00:00"), series, 20)
        for d in (1, 2, 3)
    ]
    kept = independent_outcomes([o for o in outcomes if o is not None])
    assert len(kept) == 1
    assert kept[0].suggestion.suggested_at.startswith("2026-07-01")


def test_a_later_non_overlapping_window_of_the_same_ticker_counts_again():
    series = _series(1, [100.0] + [110.0] * 40)
    early = measure(_suggestion(suggested_at="2026-07-01T16:00:00+00:00"), series, 5)
    late = measure(_suggestion(suggested_at="2026-07-20T16:00:00+00:00"), series, 5)
    kept = independent_outcomes([o for o in (early, late) if o is not None])
    assert len(kept) == 2


def test_different_tickers_never_collapse_into_each_other():
    series = _series(1, [100.0] + [110.0] * 40)
    outcomes = [
        measure(_suggestion(ticker=t, suggested_at="2026-07-01T16:00:00+00:00"), series, 20)
        for t in ("AAA", "BBB")
    ]
    assert len(independent_outcomes([o for o in outcomes if o is not None])) == 2


def test_the_independent_pick_does_not_depend_on_the_outcome():
    """Zwei überlappende Fenster, das zweite besser: es wird trotzdem das ERSTE genommen."""
    good = _series(1, [100.0] + [200.0] * 40)
    outcomes = [
        measure(_suggestion(suggested_at="2026-07-01T16:00:00+00:00"), good, 20),
        measure(_suggestion(suggested_at="2026-07-05T16:00:00+00:00"), good, 20),
    ]
    kept = independent_outcomes([o for o in outcomes if o is not None])
    assert len(kept) == 1 and kept[0].entry_date == "2026-07-02"


# --- Aggregat: beide n, und kein Urteil, das die Stichprobe nicht trägt ---------------------

def _outcomes_with_excess(excesses: list[float]) -> list:
    """Ein Outcome je Exzesswert, jeder auf eigenem Ticker (also alle unabhängig)."""
    built = []
    for i, excess in enumerate(excesses):
        series = _entry_series(100.0, 100.0 * (1 + excess))
        bench = _series(1, [50.0] * 27)  # Index flach -> Exzess == Rendite
        outcome = measure(_suggestion(ticker=f"T{i}", sector="Energy"), series, 5, bench)
        assert outcome is not None
        built.append(outcome)
    return built


def test_summary_reports_both_n_and_judges_on_the_independent_one():
    series = _entry_series(100.0, 110.0, bars=40)
    bench = _series(1, [50.0] * 42)
    overlapping = [
        measure(_suggestion(suggested_at=f"2026-07-0{d}T16:00:00+00:00"), series, 20, bench)
        for d in (1, 2, 3)
    ]
    summary = summarise([o for o in overlapping if o is not None], "Rangliste", 20)
    assert summary.n == 3
    assert summary.n_independent == 1
    assert summary.hit_rate == 1.0  # aus der unabhängigen Stichprobe, nicht aus den drei


def test_a_small_sample_is_not_declared_a_finding():
    summary = summarise(_outcomes_with_excess([0.05, 0.04, 0.06]), "Pitches", 5)
    assert summary.verdict is not None
    assert summary.verdict.verdict == "zu wenige Trades"
    assert "kein Befund" in verdict_line(summary)


def test_a_consistent_edge_is_reported_as_distinguishable():
    summary = summarise(_outcomes_with_excess([0.05, 0.06, 0.04, 0.05, 0.06, 0.05]), "X", 5)
    assert summary.verdict is not None and summary.verdict.is_significant
    assert "unterscheidbar" in verdict_line(summary)
    assert summary.hit_rate == 1.0


def test_a_losing_sample_is_stated_as_below_the_index():
    summary = summarise(_outcomes_with_excess([-0.05, -0.06, -0.04, -0.05, -0.06, -0.05]), "X", 5)
    assert (summary.mean_excess_pct or 0.0) < 0
    assert "unter dem jeweiligen Heimatindex" in verdict_line(summary)


def test_best_and_worst_come_from_the_measured_sample():
    summary = summarise(_outcomes_with_excess([0.10, -0.20, 0.02]), "X", 5)
    assert summary.best is not None and round(summary.best[1]) == 10
    assert summary.worst is not None and round(summary.worst[1]) == -20


def test_sector_concentration_is_none_when_unknown_never_zero():
    """Keine Sektorangabe heißt "unbekannt" — 0 wäre die Behauptung, es gebe kein Klumpenrisiko."""
    series = _series(1, [100.0] + [110.0] * 25)
    outcome = measure(_suggestion(sector=None), series, 5)
    assert outcome is not None
    assert sector_concentration([outcome]) is None


def test_sector_concentration_counts_the_biggest_bucket():
    series = _series(1, [100.0] + [110.0] * 25)
    built = [
        measure(_suggestion(ticker=f"T{i}", sector=sector), series, 5)
        for i, sector in enumerate(["Energy", "Energy", "Energy", "Tech"])
    ]
    assert sector_concentration([o for o in built if o is not None]) == 0.75


def test_an_empty_sample_says_so_instead_of_dividing_by_zero():
    summary = summarise([], "leer", 20)
    assert summary.n == 0 and summary.n_independent == 0
    assert summary.mean_excess_pct is None
    assert "nichts zu urteilen" in verdict_line(summary)


def test_a_sample_without_any_benchmark_refuses_to_judge():
    series = _entry_series(100.0, 130.0)
    built = [measure(_suggestion(ticker=f"F{i}.XYZ"), series, 5) for i in range(6)]
    summary = summarise([o for o in built if o is not None], "ohne Index", 5)
    assert summary.n_independent == 6
    assert summary.mean_excess_pct is None
    assert summary.mean_return_pct == pytest.approx(30.0)  # die Rohrendite bleibt sichtbar
    assert "ohne Vergleichsmaßstab" in verdict_line(summary)
