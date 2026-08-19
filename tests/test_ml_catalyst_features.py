"""Point-in-time catalyst features (v17). No network: every test builds its own frame or a
tmp_path sqlite.

The expensive mistake this guards against is a catalyst that was not yet public at `as_of`
leaking into the row. That is exactly the failure that cost five weeks on 2026-08-11, when a
champion measured 0.6195 AUC on 220 rows and delivered 0.5152 on 3281.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from equity_scout.catalyst_storage import (
    SOURCE_CALENDAR,
    SOURCE_NEWS,
    SOURCE_SCAN,
    init_catalyst_db,
    record_signals,
)
from equity_scout.ml.catalyst_features import (
    CATALYST_ACTIVE_COLUMN,
    CATALYST_FEATURE_COLUMNS,
    DUE_HORIZON_DAYS,
    LONG_WINDOW_DAYS,
    NEUTRAL,
    CatalystEvent,
    CatalystIndex,
    attach_reaction_moves,
    catalyst_events_from_db,
    catalyst_events_from_news,
    load_catalyst_index,
)

# A headline that classifies with a high strength prior, and one that classifies as chatter.
MERGER = "Acme Corp Agrees To Buy Beta Inc In All-Cash Deal"
UPGRADE = "Analysts Boost Their Forecasts On Acme Corp"


def _news(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    """(created_at, symbols, headline) rows in the archive's own shape (UTC timestamps)."""
    frame = pd.DataFrame(rows, columns=["created_at", "symbols", "headline"])
    frame["created_at"] = pd.to_datetime(frame["created_at"], utc=True, format="ISO8601")
    return frame


def _index(rows: list[tuple[str, str, str]]) -> CatalystIndex:
    return CatalystIndex(events=catalyst_events_from_news(_news(rows)), due_dates={})


def test_a_catalyst_is_invisible_until_the_day_after_it_became_known():
    """THE test. A row dated `as_of` must not see a headline stamped `as_of`; one day later it
    must. Any other behaviour makes the model unusable live."""
    index = _index([("2024-03-15T14:30:00Z", "AAA", MERGER)])

    blind = index.features("AAA", pd.Timestamp("2024-03-15"))
    assert blind[CATALYST_ACTIVE_COLUMN] == 0.0
    assert blind == NEUTRAL

    seeing = index.features("AAA", pd.Timestamp("2024-03-18"))
    assert seeing[CATALYST_ACTIVE_COLUMN] == 1.0
    assert seeing["cat_days_since"] == 3.0
    assert seeing["cat_last_strength"] == pytest.approx(0.95)


def test_utc_timestamps_are_converted_to_the_exchange_date_not_read_as_utc():
    """A wire item at 01:00 UTC belongs to the PREVIOUS New York date. Reading the UTC date would
    push roughly one in six overnight items a day forward — always in the leaking direction."""
    # 01:00 UTC is 21:00 the previous evening in New York: knowable on the 14th, but only
    # tradable on the 15th — both facts are recorded, and neither is the UTC date.
    events = catalyst_events_from_news(_news([("2024-03-15T01:00:00Z", "AAA", MERGER)]))
    assert events["AAA"][0].on == date(2024, 3, 14)
    assert events["AAA"][0].after_close is True

    # 14:30 UTC is 10:30 in New York — inside the session, so it trades the same day.
    intraday = catalyst_events_from_news(_news([("2024-03-15T14:30:00Z", "AAA", MERGER)]))
    assert intraday["AAA"][0].on == date(2024, 3, 15)
    assert intraday["AAA"][0].after_close is False


def test_an_empty_archive_and_an_unknown_ticker_both_yield_the_neutral_block():
    empty = CatalystIndex(events={}, due_dates={})
    assert empty.features("AAA", pd.Timestamp("2024-03-15")) == NEUTRAL
    blank = pd.DataFrame(columns=["created_at", "symbols", "headline"])
    assert catalyst_events_from_news(blank) == {}

    populated = _index([("2024-03-01T14:30:00Z", "AAA", MERGER)])
    assert populated.features("ZZZ", pd.Timestamp("2024-03-15")) == NEUTRAL
    assert populated.coverage(["AAA", "ZZZ"]) == 0.5
    assert populated.coverage([]) == 0.0


def test_the_block_layout_is_exactly_the_declared_columns_in_order():
    """The dataset builder NaN-fills any column a row dict is missing, so a drifting layout would
    corrupt training rows instead of failing loudly."""
    assert tuple(NEUTRAL) == CATALYST_FEATURE_COLUMNS
    index = _index([("2024-03-01T14:30:00Z", "AAA", MERGER)])
    row = index.features("AAA", pd.Timestamp("2024-03-15"))
    assert tuple(row) == CATALYST_FEATURE_COLUMNS


def test_features_are_stable_for_the_same_input():
    rows = [
        ("2024-03-01T14:30:00Z", "AAA", MERGER),
        ("2024-03-05T18:00:00Z", "AAA", UPGRADE),
    ]
    first, second = _index(rows), _index(rows)
    as_of = pd.Timestamp("2024-03-15")
    assert first.features("AAA", as_of) == second.features("AAA", as_of)
    assert first.features("AAA", as_of) == first.features("AAA", as_of)


def test_roundup_articles_never_become_catalysts():
    """"10 stocks to watch" would otherwise stamp a catalyst on every name it mentions."""
    events = catalyst_events_from_news(
        _news([("2024-03-15T14:30:00Z", "AAA,BBB,CCC,DDD,EEE", MERGER)])
    )
    assert events == {}


def test_one_story_per_class_per_day_so_republication_cannot_inflate_the_count():
    index = _index(
        [
            ("2024-03-01T13:00:00Z", "AAA", MERGER),
            ("2024-03-01T14:00:00Z", "AAA", "Acme Corp Agrees To Buy Beta Inc, Sources Say"),
            ("2024-03-01T15:00:00Z", "AAA", "Report: Acme Corp Agrees To Buy Beta Inc"),
        ]
    )
    row = index.features("AAA", pd.Timestamp("2024-03-15"))
    assert row["cat_count_30d"] == 1.0


def test_weak_classes_are_counted_but_ranked_below_strong_ones():
    """Analyst chatter is more than half the archive. It stays in the sample (it is real attention
    data) and the strength columns carry the quality distinction."""
    index = _index(
        [
            ("2024-03-01T14:00:00Z", "AAA", MERGER),
            ("2024-03-10T14:00:00Z", "AAA", UPGRADE),
        ]
    )
    row = index.features("AAA", pd.Timestamp("2024-03-15"))
    assert row["cat_count_30d"] == 2.0
    assert row["cat_last_strength"] == pytest.approx(0.30)  # the newest is the chatter
    assert row["cat_max_strength_30d"] == pytest.approx(0.95)  # the strongest is the merger


def test_windows_are_calendar_days_and_days_since_is_capped_at_the_long_window():
    index = _index(
        [
            ("2022-01-05T14:00:00Z", "AAA", MERGER),  # far outside the 365d window
            ("2024-01-10T14:00:00Z", "AAA", MERGER),  # inside 365d, outside 30d
        ]
    )
    row = index.features("AAA", pd.Timestamp("2024-03-15"))
    assert row["cat_count_365d"] == 1.0
    assert row["cat_count_30d"] == 0.0
    assert row["cat_days_since"] == 65.0

    old_only = _index([("2022-01-05T14:00:00Z", "AAA", MERGER)])
    stale = old_only.features("AAA", pd.Timestamp("2024-03-15"))
    assert stale["cat_days_since"] == float(LONG_WINDOW_DAYS)


def test_the_reaction_move_is_the_session_that_first_traded_on_the_news():
    sessions = pd.to_datetime(["2024-03-13", "2024-03-14", "2024-03-15", "2024-03-18"])
    closes = pd.DataFrame({"AAA": [100.0, 100.0, 110.0, 121.0]}, index=sessions)

    intraday = catalyst_events_from_news(_news([("2024-03-15T14:00:00Z", "AAA", MERGER)]))
    annotated = attach_reaction_moves(intraday, closes)
    assert annotated["AAA"][0].move_on == date(2024, 3, 15)
    assert annotated["AAA"][0].move == pytest.approx(0.10)

    # After the close the news trades the NEXT session, so the reaction is that session's move.
    overnight = catalyst_events_from_news(_news([("2024-03-15T21:00:00Z", "AAA", MERGER)]))
    annotated_late = attach_reaction_moves(overnight, closes)
    assert annotated_late["AAA"][0].move_on == date(2024, 3, 18)
    assert annotated_late["AAA"][0].move == pytest.approx(0.10)


def test_a_reaction_session_after_as_of_is_never_exposed_as_a_feature():
    """Belt and braces on top of the calendar argument: an `as_of` between the news and its
    reaction session must not pull that session's return into the row."""
    event = CatalystEvent(
        on=date(2024, 3, 15),
        after_close=True,
        kind="merger_acquisition",
        strength=0.95,
        move=0.10,
        move_on=date(2024, 3, 18),
    )
    index = CatalystIndex(events={"AAA": [event]}, due_dates={})
    assert index.features("AAA", pd.Timestamp("2024-03-16"))["cat_last_move"] == 0.0
    assert index.features("AAA", pd.Timestamp("2024-03-19"))["cat_last_move"] == pytest.approx(0.10)


def test_an_unmeasurable_reaction_stays_zero_instead_of_being_estimated():
    sessions = pd.to_datetime(["2024-03-13", "2024-03-14"])
    closes = pd.DataFrame({"AAA": [100.0, 110.0]}, index=sessions)
    before = catalyst_events_from_news(_news([("2024-03-12T14:00:00Z", "AAA", MERGER)]))
    after = catalyst_events_from_news(_news([("2024-04-01T14:00:00Z", "AAA", MERGER)]))
    unknown = catalyst_events_from_news(_news([("2024-03-13T14:00:00Z", "ZZZ", MERGER)]))

    for events in (before, after, unknown):
        annotated = attach_reaction_moves(events, closes)
        only = next(iter(annotated.values()))[0]
        assert only.move == 0.0
        assert only.move_on is None


def test_a_dated_catalyst_counts_only_once_the_diary_entry_itself_was_knowable():
    known_late = CatalystIndex(
        events={}, due_dates={"AAA": [(date(2024, 3, 20), date(2024, 4, 1))]}
    )
    assert known_late.features("AAA", pd.Timestamp("2024-03-15"))["cat_days_to_due"] == float(
        DUE_HORIZON_DAYS
    )

    known_early = CatalystIndex(
        events={}, due_dates={"AAA": [(date(2024, 3, 10), date(2024, 4, 1))]}
    )
    assert known_early.features("AAA", pd.Timestamp("2024-03-15"))["cat_days_to_due"] == 17.0

    past_due = CatalystIndex(
        events={}, due_dates={"AAA": [(date(2024, 1, 2), date(2024, 2, 1))]}
    )
    assert past_due.features("AAA", pd.Timestamp("2024-03-15"))["cat_days_to_due"] == float(
        DUE_HORIZON_DAYS
    )


def test_a_null_or_tz_aware_as_of_raises_instead_of_shifting_every_window():
    index = _index([("2024-03-01T14:00:00Z", "AAA", MERGER)])
    with pytest.raises(ValueError):
        index.features("AAA", None)
    with pytest.raises(ValueError):
        index.features("AAA", pd.Timestamp("2024-03-15", tz="UTC"))


def test_the_live_db_contributes_verified_move_volume_and_spread(tmp_path):
    path = tmp_path / "catalysts.db"
    init_catalyst_db(path)
    record_signals(
        path,
        [
            {
                "source": SOURCE_SCAN, "ticker": "aaa", "kind": "ignition_up",
                "seen_at": "2024-03-15T17:00:38+00:00", "dedup_key": "scan:AAA:1",
                "score": 0.92, "change_pct": 1.4022, "volume_ratio": 18.77, "spread_bp": 164.2,
            },
            {
                "source": SOURCE_NEWS, "ticker": "AAA", "kind": "merger_acquisition",
                "seen_at": "2024-03-14T11:05:07Z", "dedup_key": "news:AAA:1", "score": 0.95,
            },
            {
                "source": SOURCE_CALENDAR, "ticker": "AAA", "kind": "trial_readout",
                "seen_at": "2024-03-14T11:05:07Z", "dedup_key": "cal:AAA:1", "score": 0.5,
                "due_date": "2024-04-01",
            },
        ],
    )
    events, due = catalyst_events_from_db(path)
    assert [e.kind for e in events["AAA"]] == ["merger_acquisition", "ignition_up"]
    assert due["AAA"] == [(date(2024, 3, 14), date(2024, 4, 1))]

    row = CatalystIndex(events=events, due_dates=due).features("AAA", pd.Timestamp("2024-03-18"))
    assert row["cat_count_30d"] == 2.0
    assert row["cat_last_move"] == pytest.approx(1.4022)  # a fraction despite the column name
    assert row["cat_volume_ratio"] == pytest.approx(18.77)
    assert row["cat_spread_bp"] == pytest.approx(164.2)
    assert row["cat_days_to_due"] == 14.0


def test_a_calendar_row_is_a_diary_entry_not_a_past_catalyst():
    """A scheduled readout must supply lead time only — counting it as something that HAPPENED
    would put every waiting ticker on the same footing as one that actually moved."""
    index = CatalystIndex(
        events={}, due_dates={"AAA": [(date(2024, 3, 10), date(2024, 4, 1))]}
    )
    row = index.features("AAA", pd.Timestamp("2024-03-15"))
    assert row["cat_count_30d"] == 0.0
    assert row["cat_days_to_due"] == 17.0


def test_a_missing_catalyst_db_warns_and_creates_nothing(tmp_path, capsys):
    path = tmp_path / "absent.db"
    assert catalyst_events_from_db(path) == ({}, {})
    assert not path.exists()  # a read must never create a database as a side effect
    assert "WARNUNG" in capsys.readouterr().out


def test_an_existing_db_without_the_table_raises_rather_than_looking_empty(tmp_path):
    import sqlite3

    path = tmp_path / "wrong.db"
    sqlite3.connect(path).close()
    with pytest.raises(ValueError, match="catalyst_signals"):
        catalyst_events_from_db(path)


def test_load_catalyst_index_reads_local_files_only(tmp_path):
    """End-to-end over a two-year mini archive: no network, and the discovered years are the ones
    on disk rather than a hardcoded range."""
    from equity_scout.data.news_history import save_year

    root = tmp_path / "news"
    save_year(_news([("2023-06-01T14:00:00Z", "AAA", MERGER)]), 2023, root=root)
    save_year(_news([("2024-03-01T14:00:00Z", "AAA", UPGRADE)]), 2024, root=root)
    sessions = pd.to_datetime(["2024-02-29", "2024-03-01"])
    closes = pd.DataFrame({"AAA": [100.0, 105.0]}, index=sessions)

    index = load_catalyst_index(
        news_root=root, catalyst_db_path=tmp_path / "absent.db", closes=closes
    )
    row = index.features("AAA", pd.Timestamp("2024-03-15"))
    assert row["cat_count_365d"] == 2.0
    assert row["cat_count_30d"] == 1.0
    assert row["cat_last_move"] == pytest.approx(0.05)
    assert index.coverage(["AAA"]) == 1.0
