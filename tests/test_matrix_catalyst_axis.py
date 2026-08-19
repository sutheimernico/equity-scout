"""Catalyst axis: honest history, no look-ahead, UTC everywhere, fail-closed without events.

The look-ahead tests are the point of this file. News data is the easiest place in the project to
peek, because a headline always "explains" the move that came before it — so every path that turns
an event stamp into a bar flag is pinned by truncation and by an event that lies inside a bar.
"""
import pandas as pd
import pytest

from equity_scout.catalyst_storage import init_catalyst_db, record_signals
from equity_scout.matrix.catalyst_axis import (
    EVENT_COLUMNS,
    WINDOW_BARS,
    catalyst_age_bars,
    catalyst_window,
    empty_events,
    events_for_ticker,
    events_from_catalyst_db,
    events_from_news_archive,
    merge_events,
    select_events,
)
from equity_scout.matrix.contexts import (
    CONTEXTS,
    after_catalyst,
    after_fundamental_catalyst,
    after_hard_catalyst,
)
from equity_scout.matrix.signals import SIGNALS, catalyst_age, catalyst_volume_spike

START = "2024-01-02T14:30:00Z"  # 09:30 ET


def _bars(n: int, *, freq: str = "5min", start: str = START, volume: float = 100.0):
    index = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame(
        {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": volume},
        index=index, dtype=float,
    )


def _events(rows: list[tuple[str, str]], *, ticker: str = "AAPL") -> pd.DataFrame:
    """[(stamp, kind)] -> an event frame, bypassing the classifier."""
    return pd.DataFrame([
        {"seen_at": pd.Timestamp(stamp), "ticker": ticker, "kind": kind,
         "strength": 0.9, "source": "news"}
        for stamp, kind in rows
    ])


def _articles(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["id", "created_at", "symbols", "headline", "source"])


# --- backfill from the archive -------------------------------------------------------------

def test_archive_classification_yields_one_dated_event_per_symbol():
    news = _articles([
        {"id": "1", "created_at": "2024-01-02T14:31:00Z", "symbols": "MRNA,MRK",
         "headline": "Moderna and Merck Report Phase 3 Trial Results", "source": "benzinga"},
    ])
    events = events_from_news_archive(news)
    assert list(events["ticker"]) == ["MRNA", "MRK"]  # both sides of the deal are catalysts
    assert set(events["kind"]) == {"trial_result"}
    # The WIRE timestamp survives — a backfill stamped "now" would put every event on today.
    assert events["seen_at"].iloc[0] == pd.Timestamp("2024-01-02T14:31:00Z")


def test_archive_drops_roundups_weak_classes_and_symbol_less_items():
    news = _articles([
        {"id": "1", "created_at": "2024-01-02T14:31:00Z", "symbols": "A,B,C,D,E",
         "headline": "5 Stocks To Watch As FDA Approval Season Starts", "source": "b"},
        {"id": "2", "created_at": "2024-01-02T14:32:00Z", "symbols": "AAPL",
         "headline": "Analysts Raise Price Target On Apple", "source": "b"},
        {"id": "3", "created_at": "2024-01-02T14:33:00Z", "symbols": "",
         "headline": "FDA Approves New Treatment", "source": "b"},
        {"id": "4", "created_at": "2024-01-02T14:34:00Z", "symbols": "AAPL",
         "headline": "Apple Beats On Earnings", "source": "b"},
    ])
    events = events_from_news_archive(news)
    assert list(events["kind"]) == ["earnings_surprise"]  # only the fourth survives


def test_archive_normalises_every_stamp_to_utc():
    """The archive mixes 'Z' and offset stamps; a naive parse would misplace events by hours."""
    news = _articles([
        {"id": "1", "created_at": "2024-01-02T09:31:00-05:00", "symbols": "AAPL",
         "headline": "Apple To Be Acquired By Nobody", "source": "b"},
        {"id": "2", "created_at": "2024-01-02T15:00:00Z", "symbols": "AAPL",
         "headline": "Apple Beats On Earnings", "source": "b"},
    ])
    events = events_from_news_archive(news)
    assert str(events["seen_at"].dt.tz) == "UTC"
    assert events["seen_at"].iloc[0] == pd.Timestamp("2024-01-02T14:31:00Z")


def test_an_empty_archive_yields_an_empty_frame_with_the_right_columns():
    for news in (None, pd.DataFrame(columns=["created_at", "symbols", "headline"])):
        events = events_from_news_archive(news)
        assert events.empty
        assert tuple(events.columns) == EVENT_COLUMNS


# --- the live signal book ------------------------------------------------------------------

def _book_row(ticker: str, kind: str, stamp: str, key: str, source: str = "news") -> dict:
    return {"source": source, "ticker": ticker, "kind": kind, "seen_at": stamp,
            "dedup_key": key, "score": 0.9, "detail": "test"}


def test_db_loader_reads_scan_and_news_but_not_the_forward_calendar(tmp_path):
    path = tmp_path / "catalysts.db"
    init_catalyst_db(path)
    record_signals(path, [
        _book_row("MRNA", "trial_result", "2026-08-19T19:46:48Z", "k1"),
        _book_row("MRNA", "ignition_up", "2026-08-19T19:52:01+00:00", "k2", source="scan"),
        # 'upcoming' says a DATE is known, not that anything happened — a different question.
        _book_row("PFE", "upcoming", "2026-08-19T12:30:00+00:00", "k3", source="calendar"),
    ])
    events = events_from_catalyst_db(path)
    assert sorted(events["kind"]) == ["ignition_up", "trial_result"]
    assert str(events["seen_at"].dt.tz) == "UTC"  # 'Z' and '+00:00' land on the same clock


def test_db_loader_without_a_file_is_empty_not_an_error(tmp_path):
    assert events_from_catalyst_db(tmp_path / "missing.db").empty


def test_merge_drops_the_same_event_seen_by_two_sources():
    archive = _events([("2026-08-19T19:46:48Z", "trial_result")], ticker="MRNA")
    live = _events([("2026-08-19T19:46:48Z", "trial_result")], ticker="MRNA")
    assert len(merge_events(archive, live)) == 1
    assert merge_events(None, empty_events()).empty


def test_events_for_ticker_is_exact_membership():
    events = merge_events(
        _events([("2024-01-02T14:31:00Z", "fda_decision")], ticker="AAPL"),
        _events([("2024-01-02T14:31:00Z", "fda_decision")], ticker="AAPLX"),
    )
    assert list(events_for_ticker(events, "aapl")["ticker"]) == ["AAPL"]


# --- age and window -----------------------------------------------------------------------

def test_age_counts_bars_of_the_cell_not_minutes():
    bars = _bars(6, freq="5min")
    events = _events([(START, "fda_decision")])
    age = catalyst_age_bars(bars, events)
    assert age.tolist() == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


def test_an_event_inside_a_bar_counts_from_the_next_bar():
    """Bar labels are left-edged: a wire item at 14:31 must not flag the 14:30 bar, which was
    already trading. Getting this wrong is exactly how a news study reports free money."""
    bars = _bars(4, freq="5min")
    age = catalyst_age_bars(bars, _events([("2024-01-02T14:31:00Z", "fda_decision")]))
    assert pd.isna(age.iloc[0])
    assert age.iloc[1] == 0.0


def test_catalyst_age_is_free_of_look_ahead():
    """Truncating the frame must not change earlier ages, and an event beyond the last bar must
    be invisible — the same contract the signal suite pins for the price detectors."""
    events = _events([
        ("2024-01-02T14:40:00Z", "fda_decision"),
        ("2024-01-02T15:30:00Z", "merger_acquisition"),  # after the truncated frame ends
    ])
    full, head = _bars(20, freq="5min"), _bars(6, freq="5min")
    # fillna because NaN != NaN: "no catalyst yet" has to compare equal across the two frames.
    assert catalyst_age_bars(full, events).iloc[:6].fillna(-1.0).tolist() == \
        catalyst_age_bars(head, events).fillna(-1.0).tolist()
    assert not catalyst_window(head, _events([("2024-03-01T14:30:00Z", "fda_decision")])).any()


def test_without_history_the_age_is_nan_and_the_window_never_holds():
    bars = _bars(5)
    for events in (None, empty_events()):
        assert catalyst_age_bars(bars, events).isna().all()
        assert not catalyst_window(bars, events).any()


def test_a_ticker_without_a_catalyst_gets_no_window():
    bars = _bars(5)
    events = _events([(START, "fda_decision")], ticker="MRNA")
    assert not catalyst_window(bars, events_for_ticker(events, "AAPL")).any()


def test_the_window_is_inclusive_and_ends_after_window_bars():
    bars = _bars(WINDOW_BARS + 3, freq="5min")
    mask = catalyst_window(bars, _events([(START, "fda_decision")]))
    assert mask.iloc[0] and mask.iloc[WINDOW_BARS]
    assert not mask.iloc[WINDOW_BARS + 1]


def test_the_bar_index_timezone_does_not_change_the_mask():
    """The archive is UTC and the bars are UTC, but the same instants expressed in ET must give
    an identical mask — otherwise the axis would silently depend on how bars were loaded."""
    utc_bars = _bars(8, freq="5min")
    et_bars = utc_bars.tz_convert("America/New_York")
    events = _events([("2024-01-02T14:40:00Z", "fda_decision")])
    assert catalyst_window(utc_bars, events).tolist() == \
        catalyst_window(et_bars, events).tolist()


def test_family_selection_separates_the_kinds():
    events = _events([
        ("2024-01-02T14:30:00Z", "merger_acquisition"),
        ("2024-01-02T14:35:00Z", "earnings_surprise"),
        ("2024-01-02T14:40:00Z", "analyst_action"),
    ])
    assert len(select_events(events, family="any")) == 3
    assert list(select_events(events, family="hard")["kind"]) == ["merger_acquisition"]
    assert list(select_events(events, family="fundamental")["kind"]) == ["earnings_surprise"]
    assert select_events(events, family="hard", min_strength=0.99).empty


def test_an_unknown_family_raises_instead_of_measuring_nothing():
    with pytest.raises(ValueError):
        select_events(_events([(START, "fda_decision")]), family="pharma")


# --- signals and conditions ---------------------------------------------------------------

def test_the_age_signal_fires_only_at_the_exact_delay():
    bars = _bars(6, freq="5min")
    events = _events([(START, "fda_decision")])
    assert catalyst_age(bars, threshold=0.0, catalyst_events=events).tolist() == \
        [True, False, False, False, False, False]
    assert catalyst_age(bars, threshold=2.0, catalyst_events=events).tolist() == \
        [False, False, True, False, False, False]


def test_the_conjunction_signal_needs_the_catalyst_and_the_volume():
    bars = _bars(25, freq="5min")
    bars.iloc[-1, bars.columns.get_loc("volume")] = 400.0  # 4x the trailing median
    events = _events([(bars.index[-2].isoformat(), "fda_decision")])
    fired = catalyst_volume_spike(bars, threshold=3.0, catalyst_events=events)
    assert fired.iloc[-1] and not fired.iloc[-2]  # volume bar only, and only with the catalyst
    # Same volume spike, catalyst too old -> no signal. The conjunction is the claim.
    stale = _events([(bars.index[0].isoformat(), "fda_decision")])
    assert not catalyst_volume_spike(bars, threshold=3.0, catalyst_events=stale).any()


def test_the_catalyst_detectors_are_fail_closed_without_events():
    """Called the way the grid calls every detector — bars and threshold only. Treating a missing
    history as 'catalyst everywhere' would invent trades out of nothing."""
    bars = _bars(25, freq="5min")
    bars.iloc[-1, bars.columns.get_loc("volume")] = 400.0
    for name in ("catalyst_age", "catalyst_volume_spike"):
        spec = SIGNALS[name]
        for threshold in spec.thresholds:
            assert not spec.detect(bars, threshold=threshold).any(), name


def test_the_conditions_respect_the_family_and_the_window():
    bars = _bars(WINDOW_BARS + 3, freq="5min")
    hard = _events([(START, "merger_acquisition")])
    fundamental = _events([(START, "earnings_surprise")])
    assert after_hard_catalyst(bars, catalyst_events=hard).iloc[0]
    assert not after_hard_catalyst(bars, catalyst_events=fundamental).any()
    assert after_fundamental_catalyst(bars, catalyst_events=fundamental).iloc[0]
    assert after_catalyst(bars, catalyst_events=fundamental).iloc[0]  # 'any' takes both
    assert not after_catalyst(bars, catalyst_events=None).any()


def test_the_registry_declares_which_entries_need_catalyst_history():
    """The runner must pass the events selectively: every price-only detector takes bars and a
    threshold and nothing else, so a blanket kwarg would break twelve of them."""
    assert {n for n, s in SIGNALS.items() if "catalysts" in s.needs} == \
        {"catalyst_age", "catalyst_volume_spike"}
    assert {n for n, s in CONTEXTS.items() if "catalysts" in s.needs} == \
        {"after_catalyst", "after_hard_catalyst", "after_fundamental_catalyst"}
    for name in ("catalyst_age", "catalyst_volume_spike"):
        assert len(SIGNALS[name].thresholds) >= 4, name  # a short axis cannot form a plateau
