"""Backfill runner: per-source dispatch, dry-run shadow DB, statement burial enforced.

No network anywhere — every collector is a fake closure (the plan's canned-payload rule).
Three behaviours carry the weight:
  * a dry-run must be indistinguishable from a no-op for the REAL db while still reporting
    exact would-insert counts (so it has to dedupe against the rows already stored);
  * `--apply --source statements` must be structurally impossible, not merely discouraged
    (plan Decision 9 — the class is measured dead and the store is irreversible);
  * a `fetch_failed` on the NEWEST form4 quarter is publication lag, not a run failure
    (plan Decision 7), while the same status on an older quarter is a real defect.
"""
from __future__ import annotations

import sqlite3
import sys

import pytest

import scripts.run_history_backfill as backfill_mod
from equity_scout.evidence.backfill_form4 import HISTORY_FORM4_CURSOR_KEY
from equity_scout.evidence.base import (
    STATUS_FETCH_FAILED,
    STATUS_OK,
    STATUS_PARSE_FAILED,
    STATUS_UNCONFIGURED,
)
from equity_scout.evidence.historical_storage import HistoricalEvent, record_historical_events
from equity_scout.state_storage import get_state, set_state
from scripts.run_history_backfill import (
    BURIED_SOURCES,
    EXIT_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    SOURCES,
    main,
    run_congress,
    run_form4,
    run_statements,
    shadow_db,
)

NOW = "2026-08-07T00:00:00+00:00"


def _event(key: str, *, source: str = "congress", ticker: str = "AAA") -> HistoricalEvent:
    return HistoricalEvent(
        source=source, person="P", ticker=ticker, event_key=key, t0="2020-01-02", details={}
    )


def _hist_rows(db_path: str) -> int:
    """Row count, treating a missing table as zero — a dry-run must not even create it."""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM historical_events").fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _congress_counts(**overrides) -> dict:
    counts = {
        "filers": 3, "filers_failed": 0, "events_new": 0, "events_seen": 0,
        "index_fallback": 0, "seed_empty": 0,
        "rows": 0, "no_ticker": 0, "not_stock": 0, "no_date": 0, "malformed": 0, "duplicate": 0,
    }
    counts.update(overrides)
    return counts


def _fake_congress(events: list[HistoricalEvent], **overrides):
    """Stands in for `backfill_congress`: writes to whatever db it is handed."""
    def collector(db_path: str, *, now: str, **_kwargs) -> dict:
        new = record_historical_events(db_path, events, now=now)
        return _congress_counts(
            events_new=len(new), events_seen=len(events), rows=len(events), **overrides
        )
    return collector


def _fake_form4(statuses: dict[str, str] | None = None):
    """Stands in for `backfill_form4_quarter`: advances the cursor only on `ok`."""
    calls: list[tuple[str, str]] = []
    statuses = statuses or {}

    def collector(db_path: str, quarter: str, *, now: str, **_kwargs) -> dict:
        calls.append((quarter, now))
        status = statuses.get(quarter, STATUS_OK)
        counts = {
            "quarter": quarter, "status": status, "detail": "kaputt" if status != STATUS_OK else "",
            "url_fallback": 0, "clusters": 0, "duplicate_key": 0, "events_seen": 0,
            "events_new": 0, "boundary_candidates": 0, "mixed_issuer": 0, "rows": 0,
        }
        if status == STATUS_OK:
            new = record_historical_events(
                db_path, [_event(f"{quarter}-c", source="insider")], now=now
            )
            counts.update(clusters=1, events_seen=1, events_new=len(new), rows=7)
            set_state(db_path, key=HISTORY_FORM4_CURSOR_KEY, value=quarter)
        return counts

    return collector, calls


def _statement_counts(**overrides) -> dict:
    counts = {
        "sources_fetched": 3, "sources_failed": 0, "sources_parse_failed": 0,
        "source_errors": [], "twitter_rows": 54324, "truth_social_rows": 29469,
        "twitter_malformed": 0, "twitter_no_text": 0,
        "truth_social_malformed": 0, "truth_social_no_text": 0,
        "twitter_date_min": "2009-05-04", "twitter_date_max": "2021-01-08",
        "truth_social_date_min": "2022-02-14", "truth_social_date_max": "2026-05-02",
        "events_new": 0, "events_seen": 0, "kept": 0,
    }
    counts.update(overrides)
    return counts


def _fake_statements(events: list[HistoricalEvent] | None = None, **overrides):
    def collector(db_path: str, *, now: str, **_kwargs) -> dict:
        new = record_historical_events(db_path, events or [], now=now)
        return _statement_counts(events_new=len(new), events_seen=len(events or []), **overrides)
    return collector


def _run(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["run_history_backfill.py", *argv])
    return main()


# --- dry-run shadow -------------------------------------------------------------------

def test_shadow_db_mirrors_dedupe_keys_and_cursor_without_touching_the_original(tmp_path):
    real = str(tmp_path / "real.db")
    record_historical_events(real, [_event("k1")], now=NOW)
    set_state(real, key=HISTORY_FORM4_CURSOR_KEY, value="2010q3")

    with shadow_db(real) as shadow:
        assert shadow != real
        assert _hist_rows(shadow) == 1
        assert get_state(shadow, key=HISTORY_FORM4_CURSOR_KEY) == "2010q3"
        # A write into the shadow stays there.
        record_historical_events(shadow, [_event("k2")], now=NOW)
        assert _hist_rows(shadow) == 2

    assert _hist_rows(real) == 1


def test_shadow_db_of_a_never_created_database_leaves_no_file_behind(tmp_path):
    """A dry-run against a fresh checkout must not conjure the production db as a side
    effect — ATTACHing a missing path would create it."""
    real = str(tmp_path / "missing.db")

    with shadow_db(real) as shadow:
        assert _hist_rows(shadow) == 0

    assert not (tmp_path / "missing.db").exists()


def test_dry_run_reports_would_insert_counts_and_writes_nothing(tmp_path, monkeypatch, capsys):
    real = str(tmp_path / "real.db")
    monkeypatch.setattr(backfill_mod, "backfill_congress", _fake_congress([_event("a"), _event("b")]))

    assert _run(monkeypatch, "--source", "congress", "--db", real) == EXIT_OK

    out = capsys.readouterr().out
    assert "Würde einfügen: 2" in out
    assert "Dry-Run" in out
    assert _hist_rows(real) == 0


def test_dry_run_dedupes_against_the_rows_already_stored(tmp_path, monkeypatch, capsys):
    """Would-insert is only honest if the shadow knows what the real db already holds."""
    real = str(tmp_path / "real.db")
    record_historical_events(real, [_event("a")], now=NOW)
    monkeypatch.setattr(backfill_mod, "backfill_congress", _fake_congress([_event("a"), _event("b")]))

    assert _run(monkeypatch, "--source", "congress", "--db", real) == EXIT_OK

    assert "Würde einfügen: 1" in capsys.readouterr().out
    assert _hist_rows(real) == 1


def test_apply_writes_to_the_real_database(tmp_path, monkeypatch, capsys):
    real = str(tmp_path / "real.db")
    monkeypatch.setattr(backfill_mod, "backfill_congress", _fake_congress([_event("a"), _event("b")]))

    assert _run(monkeypatch, "--source", "congress", "--db", real, "--apply") == EXIT_OK

    out = capsys.readouterr().out
    assert "Eingefügt: 2" in out
    assert "Dry-Run" not in out
    assert _hist_rows(real) == 2


# --- Decision 9: statements are buried ------------------------------------------------

def test_apply_source_statements_is_refused_nonzero_and_never_writes(tmp_path, monkeypatch, capsys):
    real = str(tmp_path / "real.db")
    monkeypatch.setattr(
        backfill_mod, "backfill_statements",
        lambda *a, **k: pytest.fail("a refused --apply must not reach the collector"),
    )

    assert _run(monkeypatch, "--source", "statements", "--db", real, "--apply") == EXIT_REFUSED

    captured = capsys.readouterr()
    assert "class measured dead" in captured.err
    # Checked BEFORE _hist_rows, which would create the file by connecting to it.
    assert not (tmp_path / "real.db").exists(), "a refused run must not even touch the db"
    assert _hist_rows(real) == 0


def test_statements_dry_run_is_allowed_and_reports_the_measured_zero(tmp_path, monkeypatch, capsys):
    real = str(tmp_path / "real.db")
    monkeypatch.setattr(backfill_mod, "backfill_statements", _fake_statements([]))

    assert _run(monkeypatch, "--source", "statements", "--db", real) == EXIT_OK

    out = capsys.readouterr().out
    assert "Würde einfügen: 0" in out
    assert "Dry-Run" in out
    assert _hist_rows(real) == 0


def test_statements_dry_run_hits_the_shadow_even_if_the_collector_yields_events(
    tmp_path, monkeypatch
):
    """Belt and braces: the burial must hold even when the collector regains a match."""
    real = str(tmp_path / "real.db")
    monkeypatch.setattr(
        backfill_mod, "backfill_statements", _fake_statements([_event("s1", source="statement")])
    )

    assert _run(monkeypatch, "--source", "statements", "--db", real) == EXIT_OK
    assert _hist_rows(real) == 0


def test_source_help_text_carries_the_burial_reason():
    # argparse hard-wraps help at the terminal width, so compare on collapsed whitespace.
    help_text = " ".join(backfill_mod.build_parser().format_help().split())
    assert "class measured dead: 10/10 surviving events verified false" in help_text
    assert "backfill_statements.py docstring" in help_text
    assert "dry-run ONLY" in help_text


def test_every_source_is_dispatchable_and_only_statements_is_buried():
    assert set(SOURCES) == {"congress", "form4", "statements"}
    assert set(BURIED_SOURCES) == {"statements"}


def test_statements_with_every_mirror_dead_fails_loudly(tmp_path, monkeypatch, capsys):
    real = str(tmp_path / "real.db")
    monkeypatch.setattr(
        backfill_mod, "backfill_statements",
        _fake_statements(
            [], sources_fetched=0, sources_failed=3, source_errors=["u: 404"],
            twitter_rows=0, truth_social_rows=0,
        ),
    )

    assert _run(monkeypatch, "--source", "statements", "--db", real) == EXIT_FAILED
    out = capsys.readouterr().out
    assert "u: 404" in out
    assert "KEIN Negativbefund" in out


def test_statements_with_all_mirrors_schema_drifted_is_not_mistaken_for_a_negative_result(
    tmp_path, monkeypatch, capsys
):
    """`sources_fetched` is bumped BEFORE parsing — three drifted mirrors would otherwise
    report '3/3 Quellen geladen, 0 Events' and read exactly like Decision 9's real zero."""
    real = str(tmp_path / "real.db")
    monkeypatch.setattr(
        backfill_mod, "backfill_statements",
        _fake_statements(
            [], sources_fetched=3, sources_parse_failed=3,
            twitter_rows=0, truth_social_rows=0,
        ),
    )

    assert _run(monkeypatch, "--source", "statements", "--db", real) == EXIT_FAILED
    assert "KEIN Negativbefund" in capsys.readouterr().out


def test_quarters_below_one_is_rejected_instead_of_silently_doing_nothing(
    tmp_path, monkeypatch
):
    with pytest.raises(SystemExit):
        _run(monkeypatch, "--source", "form4", "--db", str(tmp_path / "real.db"), "--quarters", "0")


# --- congress -------------------------------------------------------------------------

def test_congress_seed_empty_is_a_failure_not_a_quiet_success(tmp_path, monkeypatch, capsys):
    real = str(tmp_path / "real.db")
    monkeypatch.setattr(
        backfill_mod, "backfill_congress", _fake_congress([], filers=0, seed_empty=1)
    )

    assert _run(monkeypatch, "--source", "congress", "--db", real, "--apply") == EXIT_FAILED
    assert "seed_empty" in capsys.readouterr().out


def test_congress_with_every_filer_failing_is_a_failure(tmp_path, monkeypatch, capsys):
    real = str(tmp_path / "real.db")
    monkeypatch.setattr(
        backfill_mod, "backfill_congress", _fake_congress([], filers=4, filers_failed=4)
    )

    assert _run(monkeypatch, "--source", "congress", "--db", real, "--apply") == EXIT_FAILED
    assert "4/4" in capsys.readouterr().out


def test_congress_index_fallback_is_surfaced(tmp_path, capsys):
    result = run_congress(
        str(tmp_path / "d.db"), now=NOW,
        collector=_fake_congress([_event("a")], index_fallback=1),
    )
    assert result["ok"] is True
    assert result["counts"]["index_fallback"] == 1


# --- form4 ----------------------------------------------------------------------------

def test_form4_loops_quarters_from_the_cursor_and_threads_one_now(tmp_path, monkeypatch, capsys):
    real = str(tmp_path / "real.db")
    set_state(real, key=HISTORY_FORM4_CURSOR_KEY, value="2006q1")
    collector, calls = _fake_form4()
    monkeypatch.setattr(backfill_mod, "backfill_form4_quarter", collector)

    assert _run(monkeypatch, "--source", "form4", "--db", real, "--apply", "--quarters", "3") == 0

    assert [quarter for quarter, _ in calls] == ["2006q2", "2006q3", "2006q4"]
    assert len({now for _, now in calls}) == 1, "now is threaded once from main(), never re-read"
    assert get_state(real, key=HISTORY_FORM4_CURSOR_KEY) == "2006q4"
    assert "Eingefügt: 3" in capsys.readouterr().out


def test_form4_dry_run_walks_the_shadow_cursor_and_leaves_the_real_one_alone(
    tmp_path, monkeypatch, capsys
):
    real = str(tmp_path / "real.db")
    set_state(real, key=HISTORY_FORM4_CURSOR_KEY, value="2006q1")
    collector, calls = _fake_form4()
    monkeypatch.setattr(backfill_mod, "backfill_form4_quarter", collector)

    assert _run(monkeypatch, "--source", "form4", "--db", real, "--quarters", "2") == EXIT_OK

    assert [quarter for quarter, _ in calls] == ["2006q2", "2006q3"]
    assert get_state(real, key=HISTORY_FORM4_CURSOR_KEY) == "2006q1"
    assert _hist_rows(real) == 0
    assert "Würde einfügen: 2" in capsys.readouterr().out


def test_form4_stops_at_the_newest_published_quarter(tmp_path, monkeypatch, capsys):
    """`now` sits in 2026q3, so 2026q2 is the last data set that can exist."""
    real = str(tmp_path / "real.db")
    set_state(real, key=HISTORY_FORM4_CURSOR_KEY, value="2026q1")
    collector, calls = _fake_form4()
    monkeypatch.setattr(backfill_mod, "backfill_form4_quarter", collector)

    assert _run(monkeypatch, "--source", "form4", "--db", real, "--apply", "--quarters", "8") == 0

    assert [quarter for quarter, _ in calls] == ["2026q2"]
    assert "aufgeholt" in capsys.readouterr().out.lower()


def test_form4_fetch_failed_on_the_newest_quarter_is_publication_lag_not_an_error(
    tmp_path, monkeypatch, capsys
):
    """Plan Decision 7: the SEC publishes weeks after quarter end. Cursor holds, exit 0."""
    real = str(tmp_path / "real.db")
    set_state(real, key=HISTORY_FORM4_CURSOR_KEY, value="2026q1")
    collector, _calls = _fake_form4({"2026q2": STATUS_FETCH_FAILED})
    monkeypatch.setattr(backfill_mod, "backfill_form4_quarter", collector)

    assert _run(monkeypatch, "--source", "form4", "--db", real, "--apply") == EXIT_OK

    out = capsys.readouterr().out
    assert "Publikationsverzug" in out
    assert get_state(real, key=HISTORY_FORM4_CURSOR_KEY) == "2026q1"


def test_form4_fetch_failed_on_an_old_quarter_fails_with_the_cursor_hint(
    tmp_path, monkeypatch, capsys
):
    real = str(tmp_path / "real.db")
    set_state(real, key=HISTORY_FORM4_CURSOR_KEY, value="2006q1")
    collector, _calls = _fake_form4({"2006q2": STATUS_FETCH_FAILED})
    monkeypatch.setattr(backfill_mod, "backfill_form4_quarter", collector)

    assert _run(monkeypatch, "--source", "form4", "--db", real, "--apply") == EXIT_FAILED

    out = capsys.readouterr().out
    assert HISTORY_FORM4_CURSOR_KEY in out, "a permanently broken quarter must be skippable"
    assert "2006q2" in out


def test_form4_parse_failure_stops_the_loop_before_the_next_quarter(tmp_path, monkeypatch):
    """The cursor did not advance, so a second call would refetch the same quarter forever."""
    real = str(tmp_path / "real.db")
    set_state(real, key=HISTORY_FORM4_CURSOR_KEY, value="2006q1")
    collector, calls = _fake_form4({"2006q2": STATUS_PARSE_FAILED})
    monkeypatch.setattr(backfill_mod, "backfill_form4_quarter", collector)

    assert _run(monkeypatch, "--source", "form4", "--db", real, "--apply", "--quarters", "5") == 1
    assert [quarter for quarter, _ in calls] == ["2006q2"]


def test_form4_unconfigured_user_agent_fails(tmp_path, monkeypatch, capsys):
    real = str(tmp_path / "real.db")
    set_state(real, key=HISTORY_FORM4_CURSOR_KEY, value="2006q1")
    collector, _calls = _fake_form4({"2006q2": STATUS_UNCONFIGURED})
    monkeypatch.setattr(backfill_mod, "backfill_form4_quarter", collector)

    assert _run(monkeypatch, "--source", "form4", "--db", real, "--apply") == EXIT_FAILED
    assert STATUS_UNCONFIGURED in capsys.readouterr().out


def test_form4_already_caught_up_is_a_clean_no_op(tmp_path, monkeypatch, capsys):
    real = str(tmp_path / "real.db")
    set_state(real, key=HISTORY_FORM4_CURSOR_KEY, value="2026q2")
    collector, calls = _fake_form4()
    monkeypatch.setattr(backfill_mod, "backfill_form4_quarter", collector)

    assert _run(monkeypatch, "--source", "form4", "--db", real, "--apply") == EXIT_OK
    assert calls == []
    assert "aufgeholt" in capsys.readouterr().out.lower()


def test_run_form4_keeps_per_quarter_counts_for_the_outcome_write_up(tmp_path):
    collector, _calls = _fake_form4()
    result = run_form4(
        str(tmp_path / "d.db"), now=NOW, quarters=2, collector=collector,
    )
    assert [q["quarter"] for q in result["quarters"]] == ["2006q1", "2006q2"]
    assert result["ok"] is True
    assert sum(q["events_new"] for q in result["quarters"]) == 2


def test_run_statements_never_receives_the_apply_flag():
    """`run_statements` has no way to express 'write to production' — by signature."""
    import inspect

    assert "apply" not in inspect.signature(run_statements).parameters
