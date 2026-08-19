"""Tests for the catalyst radar's layer 3 (forward-looking calendar).

No network: every payload below is a verbatim shape of the ClinicalTrials.gov v2 response as
verified live on 2026-08-19 (`fields=NCTId|BriefTitle|OverallStatus|Phase|LeadSponsorName|
PrimaryCompletionDate|EnrollmentCount`), including the two traits that decide the code —
`primaryCompletionDateStruct.date` arriving month-only for 216 of 542 studies, and sponsor
names being legal entities ("ModernaTX, Inc.") rather than issuer names ("Moderna").
"""
from __future__ import annotations

import csv

import pytest

from equity_scout import catalyst_calendar as cc
from equity_scout.catalyst_storage import SOURCE_CALENDAR, load_signals, stats
from equity_scout.earnings_storage import save_earnings_dates
from scripts.run_catalyst_calendar import run_catalyst_calendar

TODAY = "2026-08-19"
SEEN_AT = "2026-08-19T18:30:00+00:00"

# (ticker, name) rows in universe_combined.csv's real shape — listing tails, parenthetical
# name parts and dual listings all present, because all three drive the matcher.
UNIVERSE = [
    ("MRNA", "Moderna"),
    ("LLY", "Lilly (Eli)"),
    ("PFE", "Pfizer"),
    ("ZBIO", "Zenas BioPharma, Inc. - Common Stock"),
    ("AZN", "AstraZeneca PLC Ordinary Shares"),
    ("AZN.L", "AstraZeneca"),
]


def _study(
    nct_id: str,
    sponsor: str,
    due: str,
    *,
    phases: list[str] | None = None,
    title: str = "A Study",
    status: str = "RECRUITING",
    enrollment: int | None = 216,
) -> dict:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id, "briefTitle": title},
            "statusModule": {
                "overallStatus": status,
                "primaryCompletionDateStruct": {"date": due},
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": sponsor, "class": "INDUSTRY"}
            },
            "designModule": {
                "phases": phases or ["PHASE3"],
                "enrollmentInfo": {"count": enrollment},
            },
        }
    }


@pytest.fixture()
def index() -> cc.SponsorIndex:
    return cc.build_sponsor_index(UNIVERSE)


# --- field paths and dates ------------------------------------------------------------------


def test_parse_studies_reads_the_verified_field_paths() -> None:
    payload = {"studies": [_study("NCT05164094", "ModernaTX, Inc.", "2026-10-05",
                                  phases=["PHASE1", "PHASE2"], title="mRNA-1010 Study",
                                  status="ACTIVE_NOT_RECRUITING", enrollment=1407)]}
    (trial,) = cc.parse_studies(payload)
    assert trial.nct_id == "NCT05164094"
    assert trial.title == "mRNA-1010 Study"
    assert trial.sponsor == "ModernaTX, Inc."
    assert trial.phases == ("PHASE1", "PHASE2")
    assert trial.status == "ACTIVE_NOT_RECRUITING"
    assert trial.due_date == "2026-10-05"
    assert trial.month_only is False
    assert trial.enrollment == 1407


def test_parse_studies_skips_rows_without_a_usable_date_or_sponsor() -> None:
    payload = {"studies": [
        _study("NCT1", "Bayer", ""),                      # no primary completion date
        _study("NCT2", "", "2026-10-05"),                 # no lead sponsor
        {"protocolSection": {}},                          # empty section
        _study("NCT3", "Pfizer", "2026-10-05"),
    ]}
    assert [t.nct_id for t in cc.parse_studies(payload)] == ["NCT3"]


def test_month_only_date_resolves_to_the_first_of_the_month() -> None:
    # Matches ClinicalTrials.gov's own range filter: a [2026-08-19, 2026-11-17] query returned
    # 71 studies dated "2026-11" and none dated "2026-08".
    assert cc.resolve_due_date("2026-11") == "2026-11-01"
    assert cc.resolve_due_date("2026-10-05") == "2026-10-05"
    assert cc.resolve_due_date("2026") is None
    assert cc.resolve_due_date("") is None


def test_month_only_flag_reaches_the_german_detail(index: cc.SponsorIndex) -> None:
    trials = cc.parse_studies({"studies": [_study("NCT1", "Pfizer", "2026-11")]})
    signals, _, _ = cc.trial_signals(trials, index, today=TODAY, days=90, seen_at=SEEN_AT)
    (signal,) = signals
    assert signal["due_date"] == "2026-11-01"
    assert "monatsgenau" in signal["detail"]


# --- window filter ---------------------------------------------------------------------------


def test_window_filter_drops_past_and_beyond_horizon(index: cc.SponsorIndex) -> None:
    trials = cc.parse_studies({"studies": [
        _study("NCT_PAST", "Pfizer", "2026-08-18"),      # yesterday
        _study("NCT_TODAY", "Pfizer", "2026-08-19"),     # inclusive lower bound
        _study("NCT_EDGE", "Pfizer", "2026-09-18"),      # inclusive upper bound at days=30
        _study("NCT_LATE", "Pfizer", "2026-09-19"),      # one day past the horizon
    ]})
    signals, _, _ = cc.trial_signals(trials, index, today=TODAY, days=30, seen_at=SEEN_AT)
    assert [s["dedup_key"].split(":")[2] for s in signals] == ["NCT_TODAY", "NCT_EDGE"]


def test_empty_response_yields_no_signals(index: cc.SponsorIndex) -> None:
    assert cc.parse_studies({}) == []
    assert cc.trial_signals([], index, today=TODAY, days=90, seen_at=SEEN_AT) == ([], [], 0)


# --- sponsor matching ------------------------------------------------------------------------


def test_exact_match_ignores_legal_form_word_order_and_listing_tail(
    index: cc.SponsorIndex,
) -> None:
    assert cc.match_sponsor(index, "Pfizer") == ("PFE", [])
    # word order: the universe says "Lilly (Eli)", the sponsor "Eli Lilly and Company"
    assert cc.match_sponsor(index, "Eli Lilly and Company") == ("LLY", [])
    # listing tail on the universe side, a parenthetical subsidiary marker on the sponsor side
    assert cc.match_sponsor(index, "Zenas BioPharma (USA), LLC") == ("ZBIO", [])


def test_entity_tag_suffix_resolves_modernatx_to_mrna(index: cc.SponsorIndex) -> None:
    # The motivating case: MRNA jumped 127 % on 2026-08-19 and its trials are sponsored by
    # "ModernaTX, Inc.", which no exact match reaches.
    assert cc.match_sponsor(index, "ModernaTX, Inc.") == ("MRNA", [])


def test_entity_tag_rule_refuses_a_longer_tail_than_a_legal_marker(
    index: cc.SponsorIndex,
) -> None:
    # "Modernautics" is a different word, not "Moderna" plus an entity tag.
    assert cc.match_sponsor(index, "Modernautics Inc.") == (None, [])


def test_ambiguous_sponsor_produces_a_rejection_and_no_signal(index: cc.SponsorIndex) -> None:
    trials = cc.parse_studies({"studies": [
        _study("NCT1", "AstraZeneca", "2026-09-01"),
        _study("NCT2", "AstraZeneca", "2026-09-08"),   # same sponsor, second trial
    ]})
    signals, rejections, unmapped = cc.trial_signals(
        trials, index, today=TODAY, days=90, seen_at=SEEN_AT
    )
    assert signals == []
    assert unmapped == 0
    # One rejection per sponsor per run, not one per study.
    (rejection,) = rejections
    assert rejection["reason"] == cc.REASON_AMBIGUOUS
    assert rejection["ticker"] == "AstraZeneca"
    assert "AZN" in rejection["detail"] and "AZN.L" in rejection["detail"]


def test_unmapped_sponsors_are_counted_by_distinct_name_not_stored(
    index: cc.SponsorIndex,
) -> None:
    trials = cc.parse_studies({"studies": [
        _study("NCT1", "Boehringer Ingelheim", "2026-09-01"),
        _study("NCT2", "Boehringer Ingelheim", "2026-09-02"),
        _study("NCT3", "Chia Tai Tianqing Pharmaceutical Group Co., Ltd.", "2026-09-03"),
    ]})
    signals, rejections, unmapped = cc.trial_signals(
        trials, index, today=TODAY, days=90, seen_at=SEEN_AT
    )
    assert (signals, rejections) == ([], [])
    assert unmapped == 2


def test_phase_score_is_ordinal_and_labelled(index: cc.SponsorIndex) -> None:
    trials = cc.parse_studies({"studies": [
        _study("NCT3", "Pfizer", "2026-09-01", phases=["PHASE3"]),
        _study("NCT2", "Pfizer", "2026-09-02", phases=["PHASE2"]),
        _study("NCT12", "Pfizer", "2026-09-03", phases=["PHASE1", "PHASE2"]),
        _study("NCT23", "Pfizer", "2026-09-04", phases=["PHASE2", "PHASE3"]),
    ]})
    signals, _, _ = cc.trial_signals(trials, index, today=TODAY, days=90, seen_at=SEEN_AT)
    by_id = {s["dedup_key"].split(":")[2]: s for s in signals}
    assert by_id["NCT3"]["score"] > by_id["NCT2"]["score"] > by_id["NCT12"]["score"]
    assert by_id["NCT12"]["detail"].startswith("Phase 1/2:")
    assert by_id["NCT23"]["detail"].startswith("Phase 2/3:")
    assert all(0.0 <= s["score"] <= 1.0 for s in signals)


def test_signal_carries_source_kind_and_study_url(index: cc.SponsorIndex) -> None:
    trials = cc.parse_studies({"studies": [_study("NCT05164094", "Pfizer", "2026-09-01")]})
    (signal,), _, _ = cc.trial_signals(trials, index, today=TODAY, days=90, seen_at=SEEN_AT)
    assert signal["source"] == SOURCE_CALENDAR
    assert signal["kind"] == cc.KIND_TRIAL
    assert signal["url"] == "https://clinicaltrials.gov/study/NCT05164094"


# --- fetch transport -------------------------------------------------------------------------


def test_query_url_carries_the_verified_filters() -> None:
    url = cc.build_query_url(today=TODAY, days=90)
    assert url.startswith(cc.CT_API_URL)
    assert "PHASE2+OR+PHASE3" in url
    assert "LeadSponsorClass%5DINDUSTRY" in url
    assert "RANGE%5B2026-08-19%2C2026-11-17%5D" in url


def test_fetch_trials_returns_none_when_the_source_is_unreachable() -> None:
    # None is not [] on purpose: "we did not look" must never read as "no readouts are coming".
    assert cc.fetch_trials(today=TODAY, days=90, get_json=lambda url: None) is None


def test_fetch_trials_follows_the_page_token() -> None:
    pages = [
        {"studies": [_study("NCT1", "Pfizer", "2026-09-01")], "nextPageToken": "tok"},
        {"studies": [_study("NCT2", "Pfizer", "2026-09-02")]},
    ]
    seen_urls: list[str] = []

    def fake_get(url: str) -> dict:
        seen_urls.append(url)
        return pages[len(seen_urls) - 1]

    trials = cc.fetch_trials(today=TODAY, days=90, get_json=fake_get)
    assert [t.nct_id for t in trials] == ["NCT1", "NCT2"]
    assert "pageToken=tok" in seen_urls[1]


# --- earnings half ---------------------------------------------------------------------------


def test_earnings_signals_map_rows_to_the_signal_schema() -> None:
    (signal,) = cc.earnings_signals(
        [{"ticker": "MU", "earnings_date": "2026-09-23"}], seen_at=SEEN_AT
    )
    assert signal["source"] == SOURCE_CALENDAR
    assert signal["kind"] == cc.KIND_EARNINGS
    assert signal["ticker"] == "MU"
    assert signal["due_date"] == "2026-09-23"
    assert signal["dedup_key"] == "calendar:earnings:MU:2026-09-23"


# --- runner ----------------------------------------------------------------------------------


def _universe_csv(tmp_path) -> str:
    path = tmp_path / "universe.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ticker", "name", "exchange", "region", "currency", "sector"])
        for ticker, name in UNIVERSE:
            writer.writerow([ticker, name, "NASDAQ", "US", "USD", "Health Care"])
    return str(path)


def _fake_fetch(**_kwargs) -> list[cc.Trial]:
    return cc.parse_studies({"studies": [
        _study("NCT05164094", "ModernaTX, Inc.", "2026-10-05"),
        _study("NCT1", "AstraZeneca", "2026-09-01"),      # ambiguous -> rejection
        _study("NCT2", "Boehringer Ingelheim", "2026-09-01"),  # unmapped -> counted only
    ]})


def _run(tmp_path, *, apply: bool = True, fetch=_fake_fetch) -> dict:
    db = str(tmp_path / "equity_scout.db")
    save_earnings_dates(db, "PFE", ["2026-09-30"], fetched_on=TODAY)
    save_earnings_dates(db, "MRNA", ["2027-01-05"], fetched_on=TODAY)  # beyond the horizon
    return run_catalyst_calendar(
        db_path=db,
        catalyst_db_path=str(tmp_path / "catalysts.db"),
        universe_path=_universe_csv(tmp_path),
        today=TODAY,
        seen_at=SEEN_AT,
        days=90,
        apply=apply,
        fetch=fetch,
    )


def test_runner_writes_both_calendars_and_reports_honest_counts(tmp_path) -> None:
    result = _run(tmp_path)
    assert result["source_reachable"] is True
    assert result["trial_signals"] == 1
    assert result["ambiguous_sponsors"] == 1
    assert result["unmapped_sponsors"] == 1
    assert result["earnings_signals"] == 1  # the 2027 date is outside the 90-day horizon
    assert result["written"] == 2
    assert result["rejections_written"] == 1

    rows = load_signals(tmp_path / "catalysts.db")
    assert {r["ticker"] for r in rows} == {"MRNA", "PFE"}
    assert stats(tmp_path / "catalysts.db")["by_kind"] == {
        cc.KIND_TRIAL: 1, cc.KIND_EARNINGS: 1
    }


def test_runner_is_idempotent(tmp_path) -> None:
    first = _run(tmp_path)
    second = _run(tmp_path)
    assert first["written"] == 2
    assert second["written"] == 0  # same dedup keys -> nothing added
    assert second["rejections_written"] == 0  # same (source, sponsor, reason, seen_at)
    assert len(load_signals(tmp_path / "catalysts.db")) == 2


def test_rescheduled_readout_gets_its_own_row(tmp_path) -> None:
    _run(tmp_path)
    moved = cc.parse_studies({"studies": [
        _study("NCT05164094", "ModernaTX, Inc.", "2026-11-05")
    ]})
    result = _run(tmp_path, fetch=lambda **_kwargs: moved)
    assert result["written"] == 1
    due = sorted(r["due_date"] for r in load_signals(tmp_path / "catalysts.db")
                 if r["kind"] == cc.KIND_TRIAL)
    assert due == ["2026-10-05", "2026-11-05"]


def test_dry_run_writes_nothing(tmp_path) -> None:
    catalyst_db = tmp_path / "catalysts.db"
    result = _run(tmp_path, apply=False)
    assert result["trial_signals"] == 1
    assert result["written"] == 0
    assert not catalyst_db.exists()  # not even the schema is created


def test_unreachable_source_still_writes_the_earnings_half(tmp_path) -> None:
    result = _run(tmp_path, fetch=lambda **_kwargs: None)
    assert result["source_reachable"] is False
    assert result["trial_signals"] == 0
    assert result["written"] == 1
    assert [r["kind"] for r in load_signals(tmp_path / "catalysts.db")] == [cc.KIND_EARNINGS]
