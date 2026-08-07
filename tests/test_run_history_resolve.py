"""Historical forward-return resolution: synthetic panels in, honest buckets out.

Every event touched by a run must land in exactly ONE outcome bucket — measured,
counted-unresolvable, or still open. The two survivorship-relevant buckets
(`no_price_history`, `panel_gap`) are asserted explicitly because Task 6's coverage
numbers are built on them.
"""
from __future__ import annotations

import sqlite3
import sys

import pandas as pd
import pytest

import scripts.run_history_resolve as resolve_mod
from equity_scout.evidence.historical_storage import (
    HistoricalEvent,
    record_historical_events,
    unresolved_events,
)
from equity_scout.market import PricePanel
from equity_scout.ml.entry_eval import relative_forward_return
from scripts.run_history_resolve import (
    BUCKET_BAD_T0,
    BUCKET_BENCHMARK_SELF,
    BUCKET_FETCH_FAILED,
    BUCKET_NO_PRICE_HISTORY,
    BUCKET_PANEL_GAP,
    BUCKET_PARTIAL,
    BUCKET_RECHECK_CAPPED,
    BUCKET_RESOLVED,
    BUCKET_RESOLVED_THEN_BURIED,
    BUCKET_STILL_OPEN,
    BUCKET_UNMAPPABLE_SYMBOL,
    HISTORY_HORIZONS,
    apply_plan,
    main,
    resolve_batch,
    run_history_resolve,
)

NOW = "2026-08-07T00:00:00+00:00"


def _panel(periods: int = 400, start: str = "2024-01-01") -> pd.DataFrame:
    """Business-day closes where WIN outruns SPY and LOSE trails it — plain DataFrame,
    the shape `score_persons` measures against (tests/test_person_track.py:70-88)."""
    idx = pd.bdate_range(start, periods=periods)
    n = len(idx)
    return pd.DataFrame(
        {
            "SPY": [100.0 * 1.0002**i for i in range(n)],
            "WIN": [100.0 * 1.0008**i for i in range(n)],
            "LOSE": [100.0 * 0.9996**i for i in range(n)],
            "BRK-B": [100.0 * 1.0004**i for i in range(n)],
        },
        index=idx,
    )


def _panel_with(*tickers: str, periods: int = 400) -> pd.DataFrame:
    panel = _panel(periods)
    for ticker in tickers:
        panel[ticker] = panel["WIN"]
    return panel


def _raw_delisting(last_row: int = 80, periods: int = 400) -> pd.DataFrame:
    """Raw (uncleaned) closes: DEAD crashes 1 %/day and stops trading after `last_row`."""
    panel = _panel(periods)
    crash = pd.Series(
        [100.0 * 0.99**i for i in range(last_row)], index=panel.index[:last_row]
    )
    panel["DEAD"] = crash.reindex(panel.index)  # NaN tail = delisted
    return panel


def _event(event_id: int = 1, ticker: str = "WIN", t0: str = "2024-01-02", **written) -> dict:
    """An `unresolved_events` row: r_* None unless a horizon was written by an earlier run."""
    row = {"id": event_id, "source": "congress", "person": "Jane Doe", "ticker": ticker,
           "event_key": f"k{event_id}", "t0": t0, "details": {}, "created_at": NOW}
    row.update({horizon: None for horizon in HISTORY_HORIZONS})
    row.update(written)
    return row


def test_history_horizons_are_storage_columns():
    """A horizon this script measures but the store has no column for would blow up at
    write time; one the store has but this script never measures would leave rows
    partially resolved forever."""
    from equity_scout.evidence.historical_storage import RETURN_HORIZONS

    assert set(HISTORY_HORIZONS) == set(RETURN_HORIZONS)


# --- resolve_batch: the measurement --------------------------------------------------


def test_resolve_batch_fills_all_five_horizons_from_the_first_panel_date_on_or_after_t0():
    panel = _panel()
    plan = resolve_batch([_event()], panel, now=NOW)

    (resolution,) = plan.resolutions
    assert resolution.bucket == BUCKET_RESOLVED
    assert set(resolution.returns) == set(HISTORY_HORIZONS)
    # Single source of return math: identical to calling entry_eval directly at the
    # first panel date >= t0 (2024-01-02, since 2024-01-01 is the panel's first row).
    pair = panel[["WIN", "SPY"]].dropna()
    at = pd.Timestamp("2024-01-02")
    for horizon, days in HISTORY_HORIZONS.items():
        assert resolution.returns[horizon] == pytest.approx(
            relative_forward_return(pair["WIN"], pair["SPY"], at, days)
        )
    assert all(value > 0 for value in resolution.returns.values())  # WIN beats SPY


def test_resolve_batch_writes_only_the_elapsed_horizons_of_a_young_event():
    """126/252-day windows reach past the panel end — partial by design, not a failure."""
    plan = resolve_batch([_event()], _panel(periods=100), now=NOW)

    (resolution,) = plan.resolutions
    assert resolution.bucket == BUCKET_PARTIAL
    assert set(resolution.returns) == {"r_1w", "r_1m", "r_3m"}


def test_resolve_batch_never_recomputes_a_horizon_an_earlier_run_already_wrote():
    plan = resolve_batch([_event(r_1w=0.01, r_1m=-0.02)], _panel(), now=NOW)

    (resolution,) = plan.resolutions
    assert set(resolution.returns) == {"r_3m", "r_6m", "r_12m"}
    # All five are present AFTER this write, so the row becomes fully resolved.
    assert resolution.bucket == BUCKET_RESOLVED


def test_resolve_batch_counts_a_ticker_missing_from_the_panel_as_no_price_history():
    """The survivorship bucket: a delisted/renamed symbol is counted, never dropped."""
    plan = resolve_batch([_event(ticker="GONE")], _panel(), now=NOW)

    (resolution,) = plan.resolutions
    assert resolution.bucket == BUCKET_NO_PRICE_HISTORY
    assert resolution.unresolvable_reason == "no_price_history"
    assert resolution.returns == {}


def test_ffilled_delisting_fabricates_a_return_that_the_mask_turns_into_a_survivorship_gap():
    """C1, measured end to end: without `mask_stale_tail` the frozen last close of a
    delisted ticker resolves as five plausible-looking horizons — all invented past the
    delisting. With the mask, the elapsed windows survive and the rest is buried."""
    from equity_scout.data.etf_panel import clean_columns

    raw = _raw_delisting()

    fabricated = resolve_batch([_event(ticker="DEAD")], clean_columns(raw).closes, now=NOW)
    (bogus,) = fabricated.resolutions
    assert bogus.bucket == BUCKET_RESOLVED  # all five "measured" — from a flat invented tail
    assert bogus.returns["r_12m"] < -0.4  # the artifact the review measured

    honest = resolve_batch(
        [_event(ticker="DEAD")], clean_columns(raw, mask_stale_tail=True).closes, now=NOW
    )
    (resolution,) = honest.resolutions
    assert resolution.bucket == BUCKET_RESOLVED_THEN_BURIED
    assert set(resolution.returns) == {"r_1w", "r_1m", "r_3m"}  # really elapsed before the end
    assert resolution.unresolvable_reason == "no_price_history"


def test_resolve_batch_buries_a_delisted_ticker_whose_t0_precedes_no_measurable_window():
    """Delisted before even the 1w window elapsed: nothing measured, straight to the
    survivorship bucket rather than waiting forever for prices that will never come."""
    raw = _raw_delisting(last_row=80)
    from equity_scout.data.etf_panel import clean_columns

    panel = clean_columns(raw, mask_stale_tail=True).closes
    t0 = panel.index[77].date().isoformat()  # 2 sessions before DEAD stops trading

    (resolution,) = resolve_batch([_event(ticker="DEAD", t0=t0)], panel, now=NOW).resolutions
    assert resolution.bucket == BUCKET_NO_PRICE_HISTORY
    assert resolution.returns == {}


def test_resolve_batch_does_not_bury_a_ticker_that_is_merely_a_few_sessions_stale():
    """A foreign listing idle over a local holiday (or a provider one session behind) is
    NOT delisted — burial is irreversible, so the staleness margin has to absorb this."""
    from equity_scout.data.etf_panel import clean_columns

    # Last close 15 sessions before the panel end (a 3-week halt), 12m window not elapsed.
    panel = clean_columns(_raw_delisting(last_row=250, periods=265), mask_stale_tail=True).closes

    (resolution,) = resolve_batch([_event(ticker="DEAD")], panel, now=NOW).resolutions
    assert resolution.bucket == BUCKET_PARTIAL  # open, not buried
    assert set(resolution.returns) == {"r_1w", "r_1m", "r_3m", "r_6m"}
    assert resolution.unresolvable_reason is None


def test_resolve_batch_counts_an_exchange_suffixed_symbol_as_unmappable_not_missing():
    """BMW.DE -> BMW-DE is a normalization bug, not a delisting: report it, never bury it."""
    plan = resolve_batch([_event(ticker="BMW.DE")], _panel(), now=NOW)

    (resolution,) = plan.resolutions
    assert resolution.bucket == BUCKET_UNMAPPABLE_SYMBOL
    assert resolution.unresolvable_reason is None and resolution.returns == {}


def test_resolve_batch_refuses_a_panel_without_rows():
    with pytest.raises(ValueError, match="empty"):
        resolve_batch([_event()], _panel().iloc[:0], now=NOW)


def test_resolve_batch_counts_a_panel_starting_after_t0_as_panel_gap():
    """Wave-1 lesson: never silently measure from a later start (shifted window)."""
    late = _panel().loc[pd.Timestamp("2024-06-03"):]
    plan = resolve_batch([_event(t0="2024-01-02")], late, now=NOW)

    (resolution,) = plan.resolutions
    assert resolution.bucket == BUCKET_PANEL_GAP
    assert resolution.unresolvable_reason == "panel_gap"
    assert resolution.returns == {}


def test_resolve_batch_enters_on_the_next_session_for_a_weekend_t0():
    """A Saturday filing date is not a panel gap — it enters on the following Monday."""
    panel = _panel()
    plan = resolve_batch([_event(t0="2024-03-09")], panel, now=NOW)  # Saturday

    (resolution,) = plan.resolutions
    assert resolution.bucket == BUCKET_RESOLVED
    pair = panel[["WIN", "SPY"]].dropna()
    assert resolution.returns["r_1m"] == pytest.approx(
        relative_forward_return(pair["WIN"], pair["SPY"], pd.Timestamp("2024-03-11"), 21)
    )


def test_resolve_batch_leaves_an_event_open_when_no_new_window_has_elapsed():
    plan = resolve_batch([_event(r_1w=0.01)], _panel(periods=10), now=NOW)

    (resolution,) = plan.resolutions
    assert resolution.bucket == BUCKET_STILL_OPEN
    assert resolution.returns == {}
    assert resolution.unresolvable_reason is None  # open, NOT buried


def test_resolve_batch_leaves_an_event_open_when_t0_lies_past_the_panel_end():
    plan = resolve_batch([_event(t0="2030-01-02")], _panel(), now=NOW)

    assert plan.resolutions[0].bucket == BUCKET_STILL_OPEN


@pytest.mark.parametrize("bad", ["", "not-a-date", None])
def test_resolve_batch_counts_a_malformed_t0_instead_of_crashing(bad):
    plan = resolve_batch([_event(t0=bad)], _panel(), now=NOW)

    (resolution,) = plan.resolutions
    assert resolution.bucket == BUCKET_BAD_T0
    assert resolution.returns == {} and resolution.unresolvable_reason is None


def test_resolve_batch_counts_a_benchmark_self_call_instead_of_measuring_a_fake_zero():
    plan = resolve_batch([_event(ticker="SPY")], _panel(), now=NOW)

    (resolution,) = plan.resolutions
    assert resolution.bucket == BUCKET_BENCHMARK_SELF
    assert resolution.unresolvable_reason == "benchmark_self"


def test_resolve_batch_normalizes_share_class_tickers_to_the_panel_convention():
    """Disclosures say BRK.B, Yahoo says BRK-B (person_track.yf_symbol)."""
    plan = resolve_batch([_event(ticker="BRK.B")], _panel(), now=NOW)

    assert plan.resolutions[0].bucket == BUCKET_RESOLVED


def test_resolve_batch_refuses_a_panel_without_the_benchmark():
    with pytest.raises(ValueError, match="SPY"):
        resolve_batch([_event()], _panel().drop(columns=["SPY"]), now=NOW)


def test_resolve_batch_accounts_for_every_event_exactly_once():
    events = [
        _event(1, "WIN"), _event(2, "GONE"), _event(3, "SPY"),
        _event(4, "LOSE", t0="junk"), _event(5, "LOSE"),
    ]
    plan = resolve_batch(events, _panel(), now=NOW)

    assert [r.event_id for r in plan.resolutions] == [1, 2, 3, 4, 5]
    assert sum(plan.counts().values()) == len(events)


# --- apply_plan: the write -----------------------------------------------------------


def _seed(db: str, events: list[tuple[str, str]]) -> None:
    record_historical_events(
        db,
        [
            HistoricalEvent(source="congress", person="Jane Doe", ticker=ticker,
                            event_key=f"{ticker}-{t0}", t0=t0, details={})
            for ticker, t0 in events
        ],
        now=NOW,
    )


def test_apply_plan_writes_returns_and_unresolvable_reasons_once(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "2024-01-02"), ("GONE", "2024-01-02")])

    plan = resolve_batch(unresolved_events(db), _panel(), now=NOW)
    assert apply_plan(db, plan) == {"written": 2, "refused": 0}

    assert unresolved_events(db) == []  # one fully resolved, one buried
    rows = sqlite3.connect(db).execute(
        "SELECT ticker, r_1w, r_12m, resolved_at, unresolvable, unresolvable_reason"
        " FROM historical_events ORDER BY id"
    ).fetchall()
    win, gone = rows
    assert win[1] is not None and win[2] is not None and win[3] == NOW and win[4] == 0
    assert gone[1] is None and gone[4] == 1 and gone[5] == "no_price_history"

    # Re-applying the same plan must change nothing and be counted, not silently swallowed.
    assert apply_plan(db, plan) == {"written": 0, "refused": 2}


def test_apply_plan_writes_nothing_for_open_or_malformed_events(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "2024-01-02")])
    plan = resolve_batch(unresolved_events(db), _panel(periods=3), now=NOW)

    assert apply_plan(db, plan) == {"written": 0, "refused": 0}
    assert len(unresolved_events(db)) == 1


# --- run_history_resolve: the batch runner -------------------------------------------


def _fetch(panel: pd.DataFrame, seen: list | None = None):
    def fetch(tickers: list[str], start: str) -> PricePanel:
        if seen is not None:
            seen.append((tickers, start))
        return PricePanel(panel)

    return fetch


def test_run_history_resolve_dry_run_measures_but_writes_nothing(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "2024-01-02"), ("GONE", "2024-01-02")])

    result = run_history_resolve(db, now=NOW, fetch_prices=_fetch(_panel()))

    assert result["counts"][BUCKET_RESOLVED] == 1
    assert result["counts"][BUCKET_NO_PRICE_HISTORY] == 1
    assert result["written"] == 0 and result["applied"] is False
    assert result["still_open"] == 2  # nothing was written
    assert unresolved_events(db)[0]["r_1w"] is None


def test_run_history_resolve_applies_and_reports_the_survivorship_bucket(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "2024-01-02"), ("GONE", "2024-01-02")])

    result = run_history_resolve(db, now=NOW, fetch_prices=_fetch(_panel()), apply=True)

    assert result["written"] == 2 and result["still_open"] == 0
    assert result["counts"][BUCKET_NO_PRICE_HISTORY] == 1
    assert sum(result["counts"].values()) == result["events"] == 2


def test_run_history_resolve_chunks_tickers_and_always_fetches_the_benchmark(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [(t, "2024-01-02") for t in ("AAA", "BBB", "CCC", "DDD", "EEE")])
    seen: list = []

    panel = _panel_with("AAA", "BBB", "CCC", "DDD", "EEE")
    run_history_resolve(db, now=NOW, fetch_prices=_fetch(panel, seen), chunk_size=2)

    assert [tickers for tickers, _ in seen] == [
        ["AAA", "BBB", "SPY"], ["CCC", "DDD", "SPY"], ["EEE", "SPY"]
    ]
    assert all(start == "2023-12-23" for _, start in seen)  # t0 minus the lead-in


def test_run_history_resolve_counts_a_failing_chunk_instead_of_burying_its_events(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [("AAA", "2024-01-02"), ("WIN", "2024-01-02")])

    def fetch(tickers: list[str], start: str) -> PricePanel:
        if "AAA" in tickers:
            raise OSError("yahoo said no")
        return PricePanel(_panel())

    result = run_history_resolve(db, now=NOW, fetch_prices=fetch, chunk_size=1, apply=True)

    assert result["counts"][BUCKET_FETCH_FAILED] == 1
    assert result["counts"][BUCKET_RESOLVED] == 1
    # The unfetchable ticker stays OPEN — a provider outage is not a survivorship gap.
    assert [row["ticker"] for row in unresolved_events(db)] == ["AAA"]


def test_run_history_resolve_counts_a_panel_without_the_benchmark_as_a_failed_chunk(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "2024-01-02")])

    result = run_history_resolve(
        db, now=NOW, fetch_prices=_fetch(_panel().drop(columns=["SPY"])), apply=True
    )

    assert result["counts"][BUCKET_FETCH_FAILED] == 1
    assert len(unresolved_events(db)) == 1  # never buried on a broken panel


def test_run_history_resolve_limit_touches_only_the_first_events(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "2024-01-02"), ("LOSE", "2024-01-02"), ("BRK-B", "2024-01-02")])

    result = run_history_resolve(db, now=NOW, fetch_prices=_fetch(_panel()), limit=1, apply=True)

    assert result["events"] == 1
    assert result["still_open"] == 2


def test_run_history_resolve_treats_a_mass_of_missing_tickers_as_throttling(tmp_path):
    """The 2026-07-14 precedent: Yahoo throttling returns all-NaN columns that look exactly
    like delistings. Half a chunk vanishing is a provider problem — nothing may be buried,
    and no per-ticker re-check storm may follow."""
    db = str(tmp_path / "h.db")
    _seed(db, [(t, "2024-01-02") for t in ("AAA", "BBB", "CCC", "DDD")])
    seen: list = []

    result = run_history_resolve(
        db, now=NOW, fetch_prices=_fetch(_panel_with("AAA", "BBB"), seen), apply=True
    )

    assert result["counts"][BUCKET_FETCH_FAILED] == 4  # the WHOLE chunk, including AAA/BBB
    assert result["counts"][BUCKET_NO_PRICE_HISTORY] == 0
    assert len(seen) == 1  # no single-ticker re-checks after a suspected throttle
    assert len(unresolved_events(db)) == 4


def test_run_history_resolve_rechecks_a_missing_ticker_before_burying_it(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [("ZZZ", "2024-01-02")])
    seen: list = []

    def fetch(tickers: list[str], start: str) -> PricePanel:
        seen.append(tickers)
        # The batch download drops ZZZ; the targeted single fetch delivers it.
        return PricePanel(_panel_with("ZZZ") if tickers == ["ZZZ", "SPY"] else _panel())

    result = run_history_resolve(db, now=NOW, fetch_prices=fetch, apply=True)

    assert seen == [["SPY", "ZZZ"], ["ZZZ", "SPY"]]
    assert result["counts"][BUCKET_RESOLVED] == 1  # recovered, not buried
    assert unresolved_events(db) == []


def test_run_history_resolve_leaves_events_open_when_the_recheck_itself_fails(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [("ZZZ", "2024-01-02")])

    def fetch(tickers: list[str], start: str) -> PricePanel:
        if tickers == ["ZZZ", "SPY"]:
            raise OSError("throttled")
        return PricePanel(_panel())

    result = run_history_resolve(db, now=NOW, fetch_prices=fetch, apply=True)

    assert result["counts"][BUCKET_FETCH_FAILED] == 1
    assert result["counts"][BUCKET_NO_PRICE_HISTORY] == 0
    assert len(unresolved_events(db)) == 1  # unverified absence is never a burial


def test_run_history_resolve_counts_a_duplicated_panel_index_as_a_failed_chunk(tmp_path):
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "2024-01-02")])
    panel = _panel()
    doubled = pd.concat([panel, panel.iloc[[-1]]])  # provider hiccup: a repeated session

    result = run_history_resolve(db, now=NOW, fetch_prices=_fetch(doubled), apply=True)

    assert result["counts"][BUCKET_FETCH_FAILED] == 1
    assert len(unresolved_events(db)) == 1


def test_run_history_resolve_never_fetches_for_events_it_cannot_place(tmp_path):
    """All events unusable (junk t0 / unmappable symbol): the pre-filter keeps them out of
    the chunking, which is also what protects the per-chunk `min(t0)`."""
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "junk"), ("LOSE", ""), ("BMW.DE", "2024-01-02")])

    def fetch(tickers: list[str], start: str) -> PricePanel:
        raise AssertionError("nothing placeable — must not fetch")

    result = run_history_resolve(db, now=NOW, fetch_prices=fetch, apply=True)

    assert result["counts"][BUCKET_BAD_T0] == 2
    assert result["counts"][BUCKET_UNMAPPABLE_SYMBOL] == 1
    assert result["written"] == 0 and len(unresolved_events(db)) == 3  # counted, not buried


def test_run_history_resolve_delisted_event_keeps_measured_horizons_and_buries_the_rest(tmp_path):
    """C1 end to end through the store: Decision 4's partially-measured-then-buried row."""
    db = str(tmp_path / "h.db")
    _seed(db, [("DEAD", "2024-01-02")])
    from equity_scout.data.etf_panel import clean_columns

    panel = clean_columns(_raw_delisting(), mask_stale_tail=True).closes
    result = run_history_resolve(db, now=NOW, fetch_prices=_fetch(panel), apply=True)

    assert result["counts"][BUCKET_RESOLVED_THEN_BURIED] == 1
    assert result["written"] == 2  # one mark_resolved + one mark_unresolvable
    row = sqlite3.connect(db).execute(
        "SELECT r_1w, r_3m, r_6m, r_12m, unresolvable, unresolvable_reason, resolved_at"
        " FROM historical_events"
    ).fetchone()
    assert row[0] is not None and row[1] is not None  # measured windows survive the burial
    assert row[2] is None and row[3] is None  # unreachable windows stay NULL, never invented
    assert row[4] == 1 and row[5] == "no_price_history" and row[6] == NOW


def test_run_history_resolve_still_reports_a_delisting_of_an_earlier_measured_row_as_measured(
    tmp_path,
):
    """Run-log symmetry across runs: a row whose horizons were measured LAST run and that is
    buried this run is still partially measured — reporting it as a pure survivorship gap
    would understate the study's real coverage (the DB state is right either way)."""
    db = str(tmp_path / "h.db")
    _seed(db, [("DEAD", "2024-01-02")])
    from equity_scout.data.etf_panel import clean_columns

    alive = clean_columns(_raw_delisting(last_row=30, periods=30), mask_stale_tail=True).closes
    first = run_history_resolve(db, now=NOW, fetch_prices=_fetch(alive), apply=True)
    assert first["counts"][BUCKET_PARTIAL] == 1  # r_1w + r_1m elapsed, nothing else

    # Same price history, but the panel has since run a year past DEAD's last close.
    delisted = clean_columns(_raw_delisting(last_row=30, periods=400), mask_stale_tail=True).closes
    second = run_history_resolve(db, now=NOW, fetch_prices=_fetch(delisted), apply=True)

    assert second["counts"][BUCKET_RESOLVED_THEN_BURIED] == 1
    assert second["counts"][BUCKET_NO_PRICE_HISTORY] == 0
    assert second["written"] == 1  # nothing new to measure — only the burial
    row = sqlite3.connect(db).execute(
        "SELECT r_1w, r_1m, r_3m, unresolvable, unresolvable_reason FROM historical_events"
    ).fetchone()
    assert row[0] is not None and row[1] is not None and row[2] is None
    assert row[3] == 1 and row[4] == "no_price_history"


def test_run_history_resolve_caps_rechecks_and_leaves_the_rest_open(tmp_path):
    """Serial single-ticker re-checks cost 30-60s each under a throttle; past the cap the
    events wait for the next run rather than stretching the batch by hours."""
    db = str(tmp_path / "h.db")
    tickers = [f"T{i:02d}" for i in range(10)]
    _seed(db, [(t, "2024-01-02") for t in tickers])
    present = tickers[:7]  # 3 of 10 missing == exactly MAX_MISSING_SHARE, no throttle verdict
    seen: list = []

    result = run_history_resolve(
        db, now=NOW, fetch_prices=_fetch(_panel_with(*present), seen), apply=True, max_rechecks=2
    )

    assert len(seen) == 3  # one batch fetch + exactly two re-checks
    assert result["counts"][BUCKET_NO_PRICE_HISTORY] == 2  # re-checked, then buried
    assert result["counts"][BUCKET_RECHECK_CAPPED] == 1
    assert [row["ticker"] for row in unresolved_events(db)] == ["T09"]  # capped, still open
    assert sum(result["counts"].values()) == result["events"] == 10


def test_run_history_resolve_completes_a_partial_row_on_a_later_run(tmp_path):
    """Cross-run resumability: the per-column store lets a second run fill the windows that
    had not elapsed when the first run measured."""
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "2024-01-02")])

    first = run_history_resolve(db, now=NOW, fetch_prices=_fetch(_panel(periods=100)), apply=True)
    assert first["counts"][BUCKET_PARTIAL] == 1
    open_row = unresolved_events(db)[0]
    assert open_row["r_3m"] is not None and open_row["r_12m"] is None

    later = "2026-09-01T00:00:00+00:00"
    second = run_history_resolve(db, now=later, fetch_prices=_fetch(_panel()), apply=True)

    assert second["counts"][BUCKET_RESOLVED] == 1
    assert second["refused"] == 0  # only the still-missing horizons are passed
    assert unresolved_events(db) == []
    r_3m, r_12m, resolved_at = sqlite3.connect(db).execute(
        "SELECT r_3m, r_12m, resolved_at FROM historical_events"
    ).fetchone()
    assert r_3m == open_row["r_3m"]  # the first run's value stands, never recomputed
    assert r_12m is not None and resolved_at == later


def test_run_history_resolve_on_an_empty_queue_is_a_noop(tmp_path):
    db = str(tmp_path / "h.db")

    def fetch(tickers: list[str], start: str) -> PricePanel:
        raise AssertionError("must not fetch without open events")

    result = run_history_resolve(db, now=NOW, fetch_prices=fetch)

    assert result["events"] == 0 and result["still_open"] == 0


# --- CLI -----------------------------------------------------------------------------


def test_main_dry_run_prints_the_summary_and_writes_nothing(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "2024-01-02"), ("GONE", "2024-01-02")])
    monkeypatch.setattr(resolve_mod, "_fetch_price_panel", _fetch(_panel()))
    monkeypatch.setattr(sys, "argv", ["run_history_resolve.py", "--db", db])

    assert main() == 0
    out = capsys.readouterr().out
    assert "Aufgelöst: 1" in out and "no_price_history: 1" in out and "offen: 2" in out
    assert "Dry-Run" in out
    assert unresolved_events(db)[0]["r_1w"] is None


def test_main_apply_writes_and_reports(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "h.db")
    _seed(db, [("WIN", "2024-01-02")])
    monkeypatch.setattr(resolve_mod, "_fetch_price_panel", _fetch(_panel()))
    monkeypatch.setattr(sys, "argv", ["run_history_resolve.py", "--db", db, "--apply"])

    assert main() == 0
    assert "Dry-Run" not in capsys.readouterr().out
    assert unresolved_events(db) == []


def test_price_panel_loader_is_column_wise_retried_and_uses_its_own_snapshot(monkeypatch):
    """Own snapshot (never clobber sibling panels), column-wise loader (history tickers are
    global and heterogeneous), and `with_retry` around the network call."""
    import equity_scout.data.etf_panel as panel_mod
    import equity_scout.data.fetch as fetch_mod

    seen: dict = {}
    retried: list = []
    monkeypatch.setattr(
        panel_mod, "load_price_history",
        lambda tickers, **kw: seen.update(kw) or PricePanel(pd.DataFrame()),
    )
    monkeypatch.setattr(
        panel_mod, "load_etf_panel",
        lambda *a, **k: pytest.fail("history resolve must not use the common-range loader"),
    )
    monkeypatch.setattr(
        fetch_mod, "with_retry", lambda fn, **kw: retried.append(kw) or fn()
    )

    resolve_mod._fetch_price_panel(["WIN", "SPY"], "2024-01-01")

    assert seen["snapshot"] == resolve_mod.HISTORY_SNAPSHOT and seen["refresh"] is True
    assert seen["mask_stale_tail"] is True  # C1: never measure a ffilled delisting tail
    assert retried == [{"attempts": 3}]
