"""Base-rate study over `historical_events`: honest cells, or no cell at all.

The three rules these tests exist to nail down (plan Decisions 4, 2, 9):
  * a horizon is aggregated over `r_X IS NOT NULL` — NEVER over `resolved_at` and never
    with `unresolvable = 1` rows dropped, because those rows carry exactly the delisted
    names the survivorship disclaimer is about;
  * a cell may only claim an edge with min-N coverage on BOTH sides of the time split and
    an agreeing direction — otherwise `{"measurable": False, "reason": ...}`;
  * the statement class is a MEASURED zero, not an unrun one, and says so in the report.
"""
from __future__ import annotations

import json
import sqlite3
import sys

import pytest

import scripts.run_history_report as report_mod
from equity_scout.evidence.historical_storage import (
    HistoricalEvent,
    mark_resolved,
    mark_unresolvable,
    record_historical_events,
)
from equity_scout.evidence.historical_study import (
    CLAIM_DIRECTION_AGREEMENT,
    CLASS_CONGRESS,
    CLASS_INSIDER,
    CLASS_STATEMENT,
    REASON_DIRECTION_DISAGREES,
    REASON_NO_BOTH_SIDES,
    REASON_NO_DIRECTION,
    STATEMENT_MEASURED,
    SURVIVORSHIP_DISCLAIMER,
    aggregate_history,
)
from scripts.run_history_report import build_report, format_summary, main, write_report

NOW = "2026-08-07T00:00:00+00:00"
SPLIT = "2021-12-31"


def _add(
    db_path: str,
    *,
    source: str = CLASS_CONGRESS,
    ticker: str = "AAA",
    event_key: str | None = None,
    t0: str = "2020-06-01",
    person: str = "Jane Doe",
    details: dict | None = None,
    returns: dict[str, float] | None = None,
    buried: str | None = None,
) -> int:
    """Seed one event through the REAL storage API (so the per-column/one-way invariants
    hold), then return its id. `returns` before `buried` mirrors the resolver's order —
    a delisted name keeps its measured horizons."""
    key = event_key or f"{ticker}-{t0}-{source}-{person}"
    record_historical_events(
        db_path,
        [HistoricalEvent(source, person, ticker, key, t0, details or {})],
        now=NOW,
    )
    with sqlite3.connect(db_path) as con:
        event_id = con.execute(
            "SELECT id FROM historical_events WHERE source = ? AND ticker = ? AND event_key = ?",
            (source, ticker, key),
        ).fetchone()[0]
    if returns:
        assert mark_resolved(db_path, event_id, returns, now=NOW)
    if buried:
        assert mark_unresolvable(db_path, event_id, buried, now=NOW)
    return int(event_id)


def _many(db_path: str, count: int, *, t0: str, r_1m: float, **kwargs) -> None:
    for index in range(count):
        _add(
            db_path,
            ticker=f"T{index:03d}",
            t0=t0,
            event_key=f"{t0}-{index}-{kwargs.get('person', 'p')}",
            returns={"r_1m": r_1m},
            **kwargs,
        )


@pytest.fixture()
def db(tmp_path) -> str:
    return str(tmp_path / "study.db")


# --- empty / degenerate input -------------------------------------------------------


def test_empty_db_reports_zero_loudly_instead_of_raising(db):
    result = aggregate_history(db, split_date=SPLIT, min_cell_n=30)

    assert result["n_events"] == 0
    for name in (CLASS_CONGRESS, CLASS_INSIDER):
        section = result["classes"][name]
        assert section["n"] == 0
        assert section["coverage"]["total"] == 0
        assert section["overall"]["edge"]["r_1m"] == {
            "measurable": False,
            "reason": REASON_NO_BOTH_SIDES,
        }
    assert result["classes"][CLASS_STATEMENT]["n"] == 0


def test_unknown_source_is_counted_not_silently_dropped(db):
    _add(db, source="spike", ticker="ZZZ", returns={"r_1m": 0.1})

    result = aggregate_history(db, split_date=SPLIT, min_cell_n=1)

    assert result["other_sources"] == {"spike": 1}
    assert result["n_events"] == 1


# --- Decision 4: aggregate over r_X IS NOT NULL -------------------------------------


def test_hit_rate_and_mean_are_computed_per_horizon_over_non_null_returns(db):
    _add(db, ticker="AAA", event_key="a", returns={"r_1m": 0.10, "r_1w": 0.02})
    _add(db, ticker="BBB", event_key="b", returns={"r_1m": -0.02})
    _add(db, ticker="CCC", event_key="c", returns={"r_1m": 0.04})

    stats = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS]
    overall = stats["overall"]["all"]

    assert overall["r_1m"]["n"] == 3
    assert overall["r_1m"]["hit_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert overall["r_1m"]["mean_relative_return"] == pytest.approx(0.04, abs=1e-6)
    assert overall["r_1w"]["n"] == 1
    assert overall["r_1w"]["stdev"] is None  # a single measurement has no dispersion
    assert overall["r_3m"] == {
        "n": 0, "hit_rate": None, "mean_relative_return": None, "stdev": None, "stderr": None,
    }


def test_stats_carry_dispersion_so_a_cell_can_be_judged_on_its_own(db):
    for index, value in enumerate((0.10, 0.00, -0.10)):
        _add(db, ticker=f"T{index}", event_key=f"k{index}", returns={"r_1m": value})

    stats = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS][
        "overall"
    ]["all"]["r_1m"]

    assert stats["mean_relative_return"] == pytest.approx(0.0)
    assert stats["stdev"] == pytest.approx(0.1, abs=1e-6)
    assert stats["stderr"] == pytest.approx(0.1 / 3**0.5, abs=1e-6)


def test_partially_measured_row_counts_even_though_resolved_at_is_null(db):
    """`resolved_at` feeds NO published number (Decision 4) — one written horizon is a
    real measurement even while the row is still open for the other four."""
    _add(db, ticker="AAA", event_key="a", returns={"r_1w": 0.05})

    section = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS]

    assert section["overall"]["all"]["r_1w"]["n"] == 1
    assert section["coverage"]["open"] == 1
    assert section["coverage"]["partially_measured"] == 1


def test_unresolvable_rows_keep_their_measured_horizons_in_the_base_rates(db):
    """The delisted-after-a-month case: dropping it would throw away exactly the names
    the survivorship disclaimer exists for."""
    _add(db, ticker="DEAD", event_key="d", returns={"r_1w": -0.30}, buried="no_price_history")
    _add(db, ticker="ALIVE", event_key="a", returns={"r_1w": 0.10})

    section = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS]
    coverage = section["coverage"]

    assert section["overall"]["all"]["r_1w"]["n"] == 2
    assert section["overall"]["all"]["r_1w"]["hit_rate"] == pytest.approx(0.5)
    assert coverage["unresolvable"] == 1
    assert coverage["unresolvable_by_reason"] == {"no_price_history": 1}
    assert coverage["unresolvable_with_measured_horizons"] == 1


def test_coverage_reports_per_horizon_measured_counts_and_shares(db):
    _add(db, ticker="AAA", event_key="a", returns={h: 0.01 for h in ("r_1w", "r_1m", "r_3m")})
    _add(db, ticker="BBB", event_key="b", buried="no_price_history")

    coverage = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS][
        "coverage"
    ]

    assert coverage["total"] == 2
    assert coverage["measured_per_horizon"]["r_1m"] == 1
    assert coverage["measured_per_horizon"]["r_12m"] == 0
    assert coverage["coverage_per_horizon"]["r_1m"] == pytest.approx(0.5)
    assert coverage["unmeasured"] == 1
    assert coverage["fully_measured"] == 0


# --- time split ---------------------------------------------------------------------


def test_fit_and_validate_are_split_on_t0_against_split_date(db):
    _add(db, ticker="AAA", event_key="a", t0="2021-12-31", returns={"r_1m": 0.05})
    _add(db, ticker="BBB", event_key="b", t0="2022-01-01", returns={"r_1m": -0.05})

    section = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS]

    assert section["overall"]["n_fit"] == 1
    assert section["overall"]["n_validate"] == 1
    assert section["overall"]["fit"]["r_1m"]["mean_relative_return"] == pytest.approx(0.05)
    assert section["overall"]["validate"]["r_1m"]["mean_relative_return"] == pytest.approx(-0.05)


def test_malformed_split_date_is_refused_instead_of_emptying_the_fit_side(db):
    with pytest.raises(ValueError, match="split_date"):
        aggregate_history(db, split_date="2021/12/31")


def test_unparsable_t0_is_counted_and_kept_out_of_both_periods(db):
    _add(db, ticker="AAA", event_key="a", t0="not-a-date", returns={"r_1m": 0.05})

    section = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS]

    assert section["coverage"]["t0_unparsable"] == 1
    assert section["overall"]["n_fit"] == 0
    assert section["overall"]["n_validate"] == 0
    assert section["overall"]["n_undated"] == 1
    # Excluded from the pooled headline too: no gate ever sees this row, so it must not
    # move the mean. n adds up — all.n == fit.n + validate.n, always.
    assert section["overall"]["all"]["r_1m"]["n"] == 0


# --- edge claims --------------------------------------------------------------------


def test_cell_below_min_cell_n_refuses_to_claim_an_edge(db):
    _many(db, 5, t0="2020-06-01", r_1m=0.05)
    _many(db, 5, t0="2023-06-01", r_1m=0.05)

    edge = aggregate_history(db, split_date=SPLIT, min_cell_n=30)["classes"][CLASS_CONGRESS][
        "overall"
    ]["edge"]

    assert edge["r_1m"] == {"measurable": False, "reason": "n<30"}


def test_cell_without_validate_coverage_can_never_claim_an_edge(db):
    """Even with min_cell_n=1: no out-of-sample rows, no claim."""
    _many(db, 3, t0="2020-06-01", r_1m=0.05)

    edge = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS][
        "overall"
    ]["edge"]

    assert edge["r_1m"] == {"measurable": False, "reason": REASON_NO_BOTH_SIDES}


def test_direction_disagreement_between_fit_and_validate_refuses_the_edge(db):
    _many(db, 3, t0="2020-06-01", r_1m=0.05)
    _many(db, 3, t0="2023-06-01", r_1m=-0.05)

    edge = aggregate_history(db, split_date=SPLIT, min_cell_n=2)["classes"][CLASS_CONGRESS][
        "overall"
    ]["edge"]

    assert edge["r_1m"] == {"measurable": False, "reason": REASON_DIRECTION_DISAGREES}


def test_a_passing_verdict_states_the_test_performed_not_a_conclusion(db):
    _many(db, 3, t0="2020-06-01", r_1m=0.05)
    _many(db, 3, t0="2023-06-01", r_1m=0.03)

    edge = aggregate_history(db, split_date=SPLIT, min_cell_n=2)["classes"][CLASS_CONGRESS][
        "overall"
    ]["edge"]

    assert edge["r_1m"] == {
        "measurable": True,
        "direction": "positive",
        "claim": CLAIM_DIRECTION_AGREEMENT,
    }


def test_symmetric_returns_have_no_direction_to_validate(db):
    for index, value in enumerate((0.05, -0.05, 0.05, -0.05)):
        t0 = "2020-06-01" if index < 2 else "2023-06-01"
        _add(db, ticker=f"T{index}", event_key=f"k{index}", t0=t0, returns={"r_1m": value})

    edge = aggregate_history(db, split_date=SPLIT, min_cell_n=2)["classes"][CLASS_CONGRESS][
        "overall"
    ]["edge"]

    assert edge["r_1m"] == {"measurable": False, "reason": REASON_NO_DIRECTION}


def test_a_mean_that_rounds_to_zero_claims_nothing(db):
    """The stored mean is rounded to 6 decimals: a 1e-9 drift is not a direction."""
    _many(db, 2, t0="2020-06-01", r_1m=1e-9)
    _many(db, 2, t0="2023-06-01", r_1m=1e-9)

    edge = aggregate_history(db, split_date=SPLIT, min_cell_n=2)["classes"][CLASS_CONGRESS][
        "overall"
    ]["edge"]

    assert edge["r_1m"] == {"measurable": False, "reason": REASON_NO_DIRECTION}


# --- multiplicity: the noise floor is a number --------------------------------------


def test_multiplicity_counts_every_gated_cell_and_the_chance_expectation(db):
    """Class overall + both split dimensions ride on the same events, so one class with
    a single split value already produces three gated cell-horizons, not one."""
    _many(db, 2, t0="2020-06-01", r_1m=0.05,
          details={"amount_range": "$1,001 - $15,000", "chamber": "House"})
    _many(db, 2, t0="2023-06-01", r_1m=0.03,
          details={"amount_range": "$1,001 - $15,000", "chamber": "House"})

    result = aggregate_history(db, split_date=SPLIT, min_cell_n=2)

    # overall + amount_band cell + chamber cell + one person cell, r_1m only.
    assert result["n_gated_cells"] == 4
    assert result["n_direction_agreement_cells"] == 4
    assert result["expected_spurious_at_50pct"] == 2


def test_gated_cells_count_verdicts_the_gate_actually_ruled_on(db):
    _many(db, 2, t0="2020-06-01", r_1m=0.05)
    _many(db, 2, t0="2023-06-01", r_1m=0.03)

    # min_cell_n above the coverage: the gate rules on nothing, so nothing can be spurious.
    result = aggregate_history(db, split_date=SPLIT, min_cell_n=30)

    assert result["n_gated_cells"] == 0
    assert result["n_direction_agreement_cells"] == 0
    assert result["expected_spurious_at_50pct"] == 0
    assert result["claims"] == []


def test_claims_index_is_flat_and_names_where_each_claim_came_from(db):
    _many(db, 2, t0="2020-06-01", r_1m=0.05, person="Jane Doe",
          details={"chamber": "Senate"})
    _many(db, 2, t0="2023-06-01", r_1m=0.03, person="Jane Doe",
          details={"chamber": "Senate"})

    claims = aggregate_history(db, split_date=SPLIT, min_cell_n=2)["claims"]

    assert {claim["split"] for claim in claims} == {None, "amount_band", "chamber", "person"}
    chamber = next(claim for claim in claims if claim["split"] == "chamber")
    assert chamber == {
        "class": CLASS_CONGRESS,
        "split": "chamber",
        "value": "Senate",
        "horizon": "r_1m",
        "direction": "positive",
        "claim": CLAIM_DIRECTION_AGREEMENT,
        "n_fit": 2,
        "n_validate": 2,
    }
    assert next(claim for claim in claims if claim["split"] == "person")["value"] == "Jane Doe"


# --- conditional splits (deterministic details only) --------------------------------


def test_congress_splits_by_amount_band_and_chamber_including_executive_filers(db):
    """Decision 6: `details.chamber` carries chamber OR branch — executive filers are in."""
    _add(db, ticker="AAA", event_key="a", returns={"r_1m": 0.05},
         details={"amount_range": "$15,001 - $50,000", "chamber": "House"})
    _add(db, ticker="BBB", event_key="b", returns={"r_1m": 0.07},
         details={"amount_range": "$15,001 - $50,000", "chamber": "Senate"})
    _add(db, ticker="CCC", event_key="c", returns={"r_1m": -0.01},
         details={"amount_range": None, "chamber": "Executive"})

    splits = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS][
        "splits"
    ]

    assert set(splits) == {"amount_band", "chamber"}
    assert splits["amount_band"]["$15,001 - $50,000"]["n"] == 2
    assert splits["amount_band"]["unknown"]["n"] == 1
    assert set(splits["chamber"]) == {"House", "Senate", "Executive"}
    assert splits["chamber"]["Executive"]["all"]["r_1m"]["n"] == 1


def test_insider_class_reads_source_insider_and_splits_by_cluster_size_and_value(db):
    """Decision 7: the stored source is `insider`; `insider clusters` is report wording."""
    _add(db, source=CLASS_INSIDER, person="", ticker="AAA", event_key="a",
         returns={"r_1m": 0.05}, details={"n_insiders": 3, "value_band": "<$100k",
                                          "issuer_ciks": ["1"]})
    _add(db, source=CLASS_INSIDER, person="", ticker="BBB", event_key="b",
         returns={"r_1m": 0.02}, details={"n_insiders": 5, "value_band": "$100k-$1M",
                                          "issuer_ciks": ["1", "2"]})
    _add(db, source=CLASS_INSIDER, person="", ticker="CCC", event_key="c",
         returns={"r_1m": 0.02}, details={"n_insiders": 9, "value_band": "$100k-$1M",
                                          "issuer_ciks": ["3"]})

    section = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_INSIDER]

    assert section["label"] == "insider clusters"
    assert section["n"] == 3
    assert set(section["splits"]["cluster_size_band"]) == {"3", "4-5", "6+"}
    assert set(section["splits"]["value_band"]) == {"<$100k", "$100k-$1M"}
    assert section["coverage"]["mixed_issuer"] == 1
    assert section["coverage"]["notes"]


@pytest.mark.parametrize("n_insiders", [None, "drei", 2, [3]])
def test_unreadable_cluster_size_lands_in_unknown_not_in_a_neighbouring_band(db, n_insiders):
    """MIN_INSIDERS is 3, so "2" is data we do not understand — never a smaller cluster."""
    _add(db, source=CLASS_INSIDER, person="", ticker="AAA", event_key="a",
         returns={"r_1m": 0.05}, details={"n_insiders": n_insiders})

    splits = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_INSIDER][
        "splits"
    ]

    assert set(splits["cluster_size_band"]) == {"unknown"}


def test_congress_class_is_labelled_congress_and_executive_filers(db):
    label = aggregate_history(db, split_date=SPLIT)["classes"][CLASS_CONGRESS]["label"]

    assert label == "congress & executive filers"


# --- persons ------------------------------------------------------------------------


def test_person_aggregation_skips_cluster_events_without_a_person(db):
    _add(db, ticker="AAA", event_key="a", person="Jane Doe", returns={"r_1m": 0.05})
    _add(db, ticker="BBB", event_key="b", person="John Roe", returns={"r_1m": -0.05})
    _add(db, source=CLASS_INSIDER, person="", ticker="CCC", event_key="c",
         returns={"r_1m": 0.01}, details={"n_insiders": 3})

    result = aggregate_history(db, split_date=SPLIT, min_cell_n=1)

    assert set(result["classes"][CLASS_CONGRESS]["persons"]) == {"Jane Doe", "John Roe"}
    assert result["classes"][CLASS_CONGRESS]["persons"]["Jane Doe"]["n"] == 1
    assert result["classes"][CLASS_INSIDER]["persons"] == {}


# --- robustness ---------------------------------------------------------------------


def test_malformed_details_json_is_counted_not_fatal(db):
    _add(db, ticker="AAA", event_key="a", returns={"r_1m": 0.05},
         details={"chamber": "House"})
    broken = _add(db, ticker="BBB", event_key="b", returns={"r_1m": 0.05})
    with sqlite3.connect(db) as con:
        con.execute("UPDATE historical_events SET details_json = ? WHERE id = ?",
                    ("{not json", broken))

    section = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS]

    assert section["coverage"]["details_unparsable"] == 1
    assert section["n"] == 2  # the row still counts in the base rate
    assert section["splits"]["chamber"]["unknown"]["n"] == 1


def test_non_object_details_json_falls_back_to_unknown(db):
    event_id = _add(db, ticker="AAA", event_key="a", returns={"r_1m": 0.05})
    with sqlite3.connect(db) as con:
        con.execute("UPDATE historical_events SET details_json = ? WHERE id = ?",
                    ("[1, 2, 3]", event_id))

    section = aggregate_history(db, split_date=SPLIT, min_cell_n=1)["classes"][CLASS_CONGRESS]

    assert section["coverage"]["details_unparsable"] == 1
    assert section["splits"]["amount_band"]["unknown"]["n"] == 1


# --- Decision 9: the statement class is a MEASURED zero -----------------------------


def test_statement_class_publishes_the_measured_negative_result(db):
    section = aggregate_history(db, split_date=SPLIT)["classes"][CLASS_STATEMENT]

    assert section["n"] == 0
    assert section["corpus_rows"] == 78728
    assert section["candidates"] == 132
    assert section["raw_events"] == 10
    assert section["genuine"] == 0
    assert section["published"] is False
    assert section["reason"]
    assert STATEMENT_MEASURED["corpus_rows"] == 78728


def test_unexpected_statement_rows_are_flagged_loudly(db):
    _add(db, source=CLASS_STATEMENT, ticker="M", event_key="s", returns={"r_1m": 0.05})

    section = aggregate_history(db, split_date=SPLIT)["classes"][CLASS_STATEMENT]

    assert section["n"] == 1
    assert section["published"] is False
    assert "warning" in section


# --- report script ------------------------------------------------------------------


def test_report_header_carries_the_disclaimer_and_methodology(db):
    report = build_report(db, now=NOW, split_date=SPLIT, min_cell_n=30)

    assert report["generated_at"] == NOW
    assert report["survivorship_disclaimer"] == SURVIVORSHIP_DISCLAIMER
    assert len(report["methodology"]) >= 3
    assert any("panel row" in note.lower() for note in report["methodology"])
    assert any("close" in note.lower() for note in report["methodology"])
    assert report["study"]["split_date"] == SPLIT


def test_survivorship_disclaimer_is_verbatim_from_the_spec():
    spec = report_mod.REPO_ROOT / (
        "docs/superpowers/specs/2026-08-05-vision-v15-two-depots-evidence-learning.md"
    )

    def _flat(text: str) -> str:
        return " ".join(text.replace("*", "").split())

    assert _flat(SURVIVORSHIP_DISCLAIMER) in _flat(spec.read_text(encoding="utf-8"))


def test_write_report_creates_the_json_and_overwrites_it(db, tmp_path):
    out = tmp_path / "nested" / "history-study-report.json"
    report = build_report(db, now=NOW, split_date=SPLIT, min_cell_n=30)

    write_report(report, out)
    write_report(report, out)  # derived state: overwriting is the contract

    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["survivorship_disclaimer"] == SURVIVORSHIP_DISCLAIMER
    assert loaded["study"]["classes"][CLASS_STATEMENT]["raw_events"] == 10


def test_methodology_carries_the_multiplicity_numbers_of_this_run(db):
    _many(db, 2, t0="2020-06-01", r_1m=0.05)
    _many(db, 2, t0="2023-06-01", r_1m=0.03)

    report = build_report(db, now=NOW, split_date=SPLIT, min_cell_n=2)
    note = report["methodology"][-1]

    assert "50%" in note
    assert "not a significance test" in note.lower()
    assert f"{report['study']['n_gated_cells']} cell-horizons" in note
    assert f"about {report['study']['expected_spurious_at_50pct']} agreements" in note


def test_format_summary_names_every_class_and_the_dead_one(db):
    _add(db, ticker="AAA", event_key="a", returns={"r_1m": 0.05})

    text = format_summary(build_report(db, now=NOW, split_date=SPLIT, min_cell_n=30))

    assert "congress & executive filers" in text
    assert "insider clusters" in text
    assert "78728" in text  # the measured statement zero is visible in the printout
    assert "r_1m" in text
    assert "Multiples Testen" in text


def test_summary_states_the_test_performed_and_never_claims_an_edge(db):
    _many(db, 2, t0="2020-06-01", r_1m=0.05)
    _many(db, 2, t0="2023-06-01", r_1m=0.03)

    text = format_summary(build_report(db, now=NOW, split_date=SPLIT, min_cell_n=2))

    assert "Richtung in fit und validate gleich (positive) — kein Signifikanztest" in text
    assert "mit übereinstimmender Richtung" in text
    assert "belegbar" not in text
    assert "Edge" not in text


def test_summary_prints_both_per_side_hit_rates_not_only_the_pooled_one(db):
    """A pooled hit rate can hide a fit-vs-validate divergence riding on one outlier."""
    _many(db, 3, t0="2020-06-01", r_1m=0.05)
    _many(db, 3, t0="2023-06-01", r_1m=-0.05)

    text = format_summary(build_report(db, now=NOW, split_date=SPLIT, min_cell_n=2))

    assert "(fit 100.0% / validate 0.0%)" in text
    assert "stderr" in text


def test_summary_uses_singular_for_a_single_cell(db):
    _add(db, ticker="AAA", event_key="a", returns={"r_1m": 0.05},
         details={"chamber": "House", "amount_range": "$1,001 - $15,000"})

    text = format_summary(build_report(db, now=NOW, split_date=SPLIT, min_cell_n=30))

    assert "Split chamber: 1 Zelle," in text


def test_format_summary_on_an_empty_db_says_so_instead_of_crashing(db):
    text = format_summary(build_report(db, now=NOW, split_date=SPLIT, min_cell_n=30))

    assert "0 Events insgesamt" in text
    assert "keine Messung" in text


def test_main_writes_the_report_and_returns_zero(db, tmp_path, monkeypatch, capsys):
    _add(db, ticker="AAA", event_key="a", returns={"r_1m": 0.05})
    out = tmp_path / "report.json"
    monkeypatch.setattr(
        sys, "argv", ["run_history_report.py", "--db", db, "--out", str(out)]
    )

    assert main() == 0

    printed = capsys.readouterr().out
    assert "congress & executive filers" in printed
    assert json.loads(out.read_text(encoding="utf-8"))["study"]["n_events"] == 1
