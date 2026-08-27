"""Manual chain triggers: the allowlist, the log/marker/lock readers, the start command.

Everything here is pure or filesystem-only — no test starts a chain or touches systemd.
"""
from __future__ import annotations

import fcntl
from datetime import date, datetime
from pathlib import Path

from equity_scout.jobs import (
    JOBS,
    blocked_reason,
    build_start_command,
    busy_lock,
    job_status,
    lock_held,
    marker_value,
    parse_progress,
    tail_lines,
)

DAILY_LOG = """[2026-08-07T18:00:00+02:00] ===== daily_copilot start =====
[2026-08-07T18:00:01+02:00] START radar
[2026-08-07T18:01:30+02:00] OK radar
[2026-08-07T18:01:31+02:00] START insights
[2026-08-07T18:04:10+02:00] FAILED insights (exit 1) — continuing
[2026-08-07T18:04:11+02:00] START earnings
"""


def test_parse_progress_reports_the_running_step_and_the_finished_count() -> None:
    progress = parse_progress(DAILY_LOG, JOBS["daily"].steps)
    assert progress["current"] == "earnings"
    assert progress["done_count"] == 2  # radar OK + insights FAILED are both finished
    assert progress["failed"] == ["insights"]
    assert progress["expected_total"] == 13  # 12 + opportunities (2026-08-27)
    assert progress["started_at"] == "2026-08-07T18:00:00+02:00"
    assert progress["current_since"] == "2026-08-07T18:04:11+02:00"


def test_parse_progress_ignores_everything_before_the_last_session_start() -> None:
    text = DAILY_LOG + """[2026-08-08T18:00:00+02:00] ===== daily_copilot start =====
[2026-08-08T18:00:01+02:00] START radar
"""
    progress = parse_progress(text, JOBS["daily"].steps)
    assert progress["current"] == "radar"
    assert progress["done_count"] == 0
    assert progress["failed"] == []


def test_parse_progress_on_a_finished_run_has_no_current_step() -> None:
    text = DAILY_LOG + "[2026-08-07T18:26:00+02:00] OK earnings\n"
    progress = parse_progress(text, JOBS["daily"].steps)
    assert progress["current"] is None
    assert progress["done_count"] == 3


def test_parse_progress_on_an_empty_log_is_all_zero() -> None:
    progress = parse_progress("", JOBS["daily"].steps)
    assert progress["current"] is None
    assert progress["done_count"] == 0
    assert progress["started_at"] is None


def test_parse_progress_ignores_chain_stdout_between_the_step_markers() -> None:
    # The chains redirect each step's output into the same log; a line that merely
    # contains the word START must not be read as a step marker.
    text = DAILY_LOG + "Traceback: START of something unrelated\n"
    progress = parse_progress(text, JOBS["daily"].steps)
    assert progress["current"] == "earnings"


def test_tail_lines_returns_the_last_lines_only(tmp_path) -> None:
    log = tmp_path / "x.log"
    log.write_text("\n".join(f"line {i}" for i in range(100)) + "\n")
    assert tail_lines(log, 3) == ["line 97", "line 98", "line 99"]


def test_tail_lines_on_a_missing_file_is_empty(tmp_path) -> None:
    assert tail_lines(tmp_path / "nope.log", 5) == []


def test_lock_held_is_false_for_a_free_and_a_missing_lock(tmp_path) -> None:
    assert lock_held(tmp_path / "missing.lock") is False
    free = tmp_path / "free.lock"
    free.write_text("stale content from a finished run\n")
    assert lock_held(free) is False  # the file survives the run, the flock does not


def test_lock_held_is_true_while_another_handle_holds_the_flock(tmp_path) -> None:
    held = tmp_path / "held.lock"
    held.write_text("")
    with held.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert lock_held(held) is True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    assert lock_held(held) is False


def test_marker_value_reads_and_strips(tmp_path) -> None:
    marker = tmp_path / "daily_last_run"
    marker.write_text("2026-08-07\n")
    assert marker_value(marker) == "2026-08-07"
    assert marker_value(tmp_path / "absent") is None


def test_blocked_reason_reports_already_ran_for_todays_marker(tmp_path) -> None:
    (tmp_path / ".state").mkdir()
    (tmp_path / ".state" / "daily_last_run").write_text("2026-08-10")
    # 2026-08-10 is a Monday, so the weekend guard is not what blocks here.
    assert blocked_reason(JOBS["daily"], tmp_path, today=date(2026, 8, 10)) == "already_ran"


def test_blocked_reason_reports_weekend_when_the_marker_is_stale(tmp_path) -> None:
    (tmp_path / ".state").mkdir()
    (tmp_path / ".state" / "daily_last_run").write_text("2026-08-07")
    # 2026-08-09 is a Sunday: the wrapper's weekday guard would skip the run.
    assert blocked_reason(JOBS["daily"], tmp_path, today=date(2026, 8, 9)) == "weekend"


def test_blocked_reason_is_none_on_a_weekday_with_a_stale_marker(tmp_path) -> None:
    (tmp_path / ".state").mkdir()
    (tmp_path / ".state" / "daily_last_run").write_text("2026-08-07")
    assert blocked_reason(JOBS["daily"], tmp_path, today=date(2026, 8, 10)) is None


def test_the_full_job_is_never_marker_blocked(tmp_path) -> None:
    # It has no marker of its own: it is the explicit "redo everything" button and
    # always runs forced, so its phases' markers must not gate the button.
    assert blocked_reason(JOBS["full"], tmp_path, today=date(2026, 8, 9)) is None


def test_busy_lock_names_the_blocking_sub_chain_for_the_full_job(tmp_path) -> None:
    state = tmp_path / ".state"
    state.mkdir()
    daily = state / "daily.lock"
    daily.write_text("")
    with daily.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert busy_lock(JOBS["full"], tmp_path) == ".state/daily.lock"
        assert busy_lock(JOBS["daily"], tmp_path) == ".state/daily.lock"
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    assert busy_lock(JOBS["full"], tmp_path) is None


def test_build_start_command_is_a_systemd_unit_with_no_request_data() -> None:
    cmd = build_start_command(JOBS["daily"], Path("/repo"), force=False, unit_suffix="1")
    assert cmd[:3] == ["systemd-run", "--user", "--collect"]
    assert "--unit=es-job-daily-1" in cmd
    assert "--working-directory=/repo" in cmd
    assert cmd[-2:] == ["/repo/scripts/run_daily_guarded.sh", "cockpit"]
    assert "--setenv=EQUITY_SCOUT_FORCE=1" not in cmd


def test_build_start_command_passes_force_as_an_env_var() -> None:
    cmd = build_start_command(JOBS["full"], Path("/repo"), force=True, unit_suffix="2")
    assert "--setenv=EQUITY_SCOUT_FORCE=1" in cmd
    assert cmd[-2:] == ["/repo/scripts/run_full_refresh.sh", "cockpit"]


def test_job_status_shape_for_the_daily_job(tmp_path) -> None:
    (tmp_path / ".state").mkdir()
    (tmp_path / ".state" / "daily_last_run").write_text("2026-08-07")
    (tmp_path / "copilot.log").write_text(DAILY_LOG)
    status = job_status(JOBS["daily"], tmp_path, now=datetime(2026, 8, 9, 12, 0))
    assert status["key"] == "daily"
    assert status["label"] == "Tages-Update"
    assert status["running"] is False
    assert status["blocked"] == "weekend"
    assert status["last_run"] == "2026-08-07"
    assert status["progress"]["current"] == "earnings"
    assert status["tail"][-1].startswith("[2026-08-07T18:04:11")
    assert "sub_runs" not in status


def test_job_status_for_the_full_job_lists_the_three_phase_markers(tmp_path) -> None:
    state = tmp_path / ".state"
    state.mkdir()
    (state / "daily_last_run").write_text("2026-08-07")
    (state / "nightly_last_run").write_text("2026-08-08")
    status = job_status(JOBS["full"], tmp_path, now=datetime(2026, 8, 9, 12, 0))
    assert status["sub_runs"] == {"scout": None, "daily": "2026-08-07", "nightly": "2026-08-08"}
    assert status["blocked"] is None


def test_job_status_tails_the_running_phases_own_log_for_the_full_job(tmp_path) -> None:
    # full_refresh.log carries only the three phase markers, so while "scout" runs the
    # useful lines live in scout_full.log.
    (tmp_path / "full_refresh.log").write_text(
        "[2026-08-09T21:00:00+02:00] ===== full_refresh start ===== (trigger: cockpit)\n"
        "[2026-08-09T21:00:01+02:00] START scout\n"
    )
    (tmp_path / "scout_full.log").write_text("screening 1200 tickers\n")
    status = job_status(JOBS["full"], tmp_path, now=datetime(2026, 8, 9, 21, 5))
    assert status["progress"]["current"] == "scout"
    assert status["tail"] == ["screening 1200 tickers"]
