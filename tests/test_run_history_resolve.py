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
    BUCKET_RESOLVED,
    BUCKET_STILL_OPEN,
    HORIZON_DAYS,
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


def _event(event_id: int = 1, ticker: str = "WIN", t0: str = "2024-01-02", **written) -> dict:
    """An `unresolved_events` row: r_* None unless a horizon was written by an earlier run."""
    row = {"id": event_id, "source": "congress", "person": "Jane Doe", "ticker": ticker,
           "event_key": f"k{event_id}", "t0": t0, "details": {}, "created_at": NOW}
    row.update({horizon: None for horizon in HORIZON_DAYS})
    row.update(written)
    return row


# --- resolve_batch: the measurement --------------------------------------------------


def test_resolve_batch_fills_all_five_horizons_from_the_first_panel_date_on_or_after_t0():
    panel = _panel()
    plan = resolve_batch([_event()], panel, now=NOW)

    (resolution,) = plan.resolutions
    assert resolution.bucket == BUCKET_RESOLVED
    assert set(resolution.returns) == set(HORIZON_DAYS)
    # Single source of return math: identical to calling entry_eval directly at the
    # first panel date >= t0 (2024-01-02, since 2024-01-01 is the panel's first row).
    pair = panel[["WIN", "SPY"]].dropna()
    at = pd.Timestamp("2024-01-02")
    for horizon, days in HORIZON_DAYS.items():
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

    run_history_resolve(db, now=NOW, fetch_prices=_fetch(_panel(), seen), chunk_size=2)

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
    assert retried == [{"attempts": 3}]
