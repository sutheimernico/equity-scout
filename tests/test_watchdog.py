"""Dead-man watchdog (v12 W1): a silently dead chain must make noise — once per cooldown."""
from __future__ import annotations

import json

from datetime import datetime, timezone

from equity_scout.state_storage import record_heartbeat
from equity_scout.watchdog import alerts_due, mark_alerted, overdue_chains

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _db(tmp_path) -> str:
    return str(tmp_path / "main.db")


def test_stale_heartbeat_is_overdue_fresh_is_not(tmp_path) -> None:
    db = _db(tmp_path)
    record_heartbeat(db, "daily", now="2026-07-20T18:05:00+00:00")  # 17.9h ago -> fresh
    record_heartbeat(db, "nightly", now="2026-07-19T02:35:00+00:00")  # 57h ago -> overdue
    record_heartbeat(db, "crypto", now="2026-07-21T11:45:00+00:00")  # 15min -> fresh
    overdue = overdue_chains(db, now=NOW)
    assert [o["chain"] for o in overdue] == ["nightly"]
    assert overdue[0]["overdue_hours"] > 26


def test_chain_without_any_heartbeat_is_never_alarmed(tmp_path) -> None:
    assert overdue_chains(_db(tmp_path), now=NOW) == []


def test_nightly_on_monday_is_not_overdue_after_its_saturday_slot(tmp_path) -> None:
    """Regression (measured 2026-08-10): the nightly cadence is Tue–Sat, so on Sunday and
    Monday a 48–72h old heartbeat is exactly on schedule — the flat 26h SLA cried wolf."""
    db = _db(tmp_path)
    # Sat 2026-08-08 02:32 CEST = 00:32 UTC — the chain's own log line for that run.
    record_heartbeat(db, "nightly", now="2026-08-08T00:32:00+00:00")
    monday = datetime(2026, 8, 10, 16, 50, tzinfo=timezone.utc)  # Mon 18:50 CEST, 64h later
    assert overdue_chains(db, now=monday) == []


def test_nightly_missing_its_due_slot_is_overdue_with_the_slot_named(tmp_path) -> None:
    db = _db(tmp_path)
    record_heartbeat(db, "nightly", now="2026-08-08T00:32:00+00:00")  # last: Sat
    # Tue 2026-08-11 08:00 CEST — the Tuesday 02:30 slot came and went unanswered.
    overdue = overdue_chains(db, now=datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc))
    assert [o["chain"] for o in overdue] == ["nightly"]
    assert overdue[0]["missed_slot"].startswith("2026-08-11T02:30")


def test_daily_on_sunday_is_not_overdue_after_its_friday_slot(tmp_path) -> None:
    db = _db(tmp_path)
    record_heartbeat(db, "daily", now="2026-08-07T16:10:00+00:00")  # Fri 18:10 CEST
    sunday = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)  # Sun 12:00 CEST, 42h later
    assert overdue_chains(db, now=sunday) == []


def test_heartbeat_just_before_the_systemd_slot_still_answers_it(tmp_path) -> None:
    """The chain stamps its heartbeat when it FINISHES (02:32 for a 02:30 cron start), which
    precedes the 02:35 systemd slot — the slot must be the earliest trigger, not the latest."""
    db = _db(tmp_path)
    record_heartbeat(db, "nightly", now="2026-08-11T00:32:00+00:00")  # Tue 02:32 CEST
    assert overdue_chains(db, now=datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)) == []


def test_cooldown_suppresses_repeat_alerts(tmp_path) -> None:
    db = _db(tmp_path)
    record_heartbeat(db, "crypto", now="2026-07-21T06:00:00+00:00")  # 6h ago -> overdue (SLA 2h)
    overdue = overdue_chains(db, now=NOW)
    assert [o["chain"] for o in overdue] == ["crypto"]

    due = alerts_due(db, overdue, now=NOW)
    assert [d["chain"] for d in due] == ["crypto"]
    mark_alerted(db, [d["chain"] for d in due], now=NOW)

    assert alerts_due(db, overdue_chains(db, now=NOW), now=NOW) == []  # inside cooldown


def test_run_watchdog_cli_sends_once_then_respects_cooldown(tmp_path, monkeypatch) -> None:
    import sys
    from datetime import timedelta

    import scripts.run_watchdog as wd

    db = str(tmp_path / "main.db")
    stale = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    record_heartbeat(db, "crypto", now=stale)  # SLA 2h -> overdue
    for var in ("COPILOT_TG_CHAT_ID_INTRADAY", "COPILOT_TG_CHAT_ID_DAILY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COPILOT_TG_BOT_TOKEN", "t")
    monkeypatch.setenv("COPILOT_TG_CHAT_ID", "1")
    sent: list[str] = []
    monkeypatch.setattr(
        wd, "send_message", lambda token, chat_id, text: sent.append(text) or 1
    )
    monkeypatch.setattr(sys, "argv", ["run_watchdog.py", "--db", db])

    assert wd.main() == 0
    assert len(sent) == 1 and "crypto" in sent[0]
    assert wd.main() == 0  # second run inside the cooldown
    assert len(sent) == 1


def test_run_watchdog_cli_records_its_own_heartbeat(tmp_path, monkeypatch) -> None:
    import sys

    import scripts.run_watchdog as wd
    from equity_scout.state_storage import get_state

    db = str(tmp_path / "main.db")
    monkeypatch.delenv("COPILOT_TG_BOT_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_watchdog.py", "--db", db])
    assert wd.main() == 0
    assert get_state(db, key="heartbeat_watchdog") is not None


def test_gapfade_missing_its_morning_slot_is_overdue(tmp_path) -> None:
    """The lane runs Mon-Fri at 15:00 Berlin only, so it must be judged on missed slots,
    not on heartbeat age — on a Monday noon its last legitimate beat is from Friday."""
    db = _db(tmp_path)
    record_heartbeat(db, "gapfade", now="2026-07-20T13:05:00+00:00")  # Mon 15:05 Berlin
    monday_evening = datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)
    assert [o["chain"] for o in overdue_chains(db, now=monday_evening)] == []

    tuesday_evening = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    overdue = overdue_chains(db, now=tuesday_evening)
    assert "gapfade" in [o["chain"] for o in overdue]


def test_gapfade_on_the_weekend_is_not_overdue(tmp_path) -> None:
    """Saturday and Sunday have no slot; the Friday beat must stay good until Monday —
    the same false alarm the nightly chain taught us about on 2026-08-10."""
    db = _db(tmp_path)
    record_heartbeat(db, "gapfade", now="2026-07-17T13:05:00+00:00")  # Fri 15:05 Berlin
    sunday = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    assert [o["chain"] for o in overdue_chains(db, now=sunday)] == []


def test_a_lane_that_never_beat_once_is_never_alarmed(tmp_path) -> None:
    """The honest limit of this watchdog, pinned deliberately: `gapfade` failed on EVERY
    slot from its first day (2026-08-17..20), so it never wrote a first heartbeat and no
    schedule entry could have raised the alarm. Only a chain that once worked can be
    detected as broken here — a never-started chain needs a different check."""
    db = _db(tmp_path)
    record_heartbeat(db, "daily", now="2026-07-20T18:05:00+00:00")
    assert "gapfade" not in [o["chain"] for o in overdue_chains(db, now=NOW)]


# --- the scheduler's own outage (2026-08-23) -------------------------------------------
# The heartbeat SLAs cannot see this one: the watchdog rides in the same cron command as the
# crypto lane and runs AFTER it, so on the first run back every heartbeat it reads is
# seconds old. Measured on the real box: away 2026-08-22 19:01 -> 08-23 03:30 and again
# 03:56 -> 13:48, and not one chain reported anything.

def test_a_slept_through_afternoon_is_detected_and_priced_in_trading_minutes(tmp_path) -> None:
    from zoneinfo import ZoneInfo

    from equity_scout.watchdog import scheduler_gap

    berlin = ZoneInfo("Europe/Berlin")
    db = _db(tmp_path)
    # Tuesday 16:00 Berlin = 10:00 ET, back at 21:00 Berlin = 15:00 ET -> 300 session minutes
    record_heartbeat(db, "watchdog", now=datetime(2026, 8, 18, 16, 0, tzinfo=berlin).isoformat())
    gap = scheduler_gap(db, now=datetime(2026, 8, 18, 21, 0, tzinfo=berlin))

    assert gap is not None
    assert gap["session_minutes"] == 300
    assert gap["hours"] == 5.0


def test_the_same_length_of_outage_over_a_weekend_costs_nothing(tmp_path) -> None:
    """Duration is the wrong headline. The real gap on 2026-08-22/23 was 8.5 hours and cost
    zero trading minutes; an alert that only reported hours would read like an emergency."""
    from zoneinfo import ZoneInfo

    from equity_scout.watchdog import build_gap_text, scheduler_gap

    berlin = ZoneInfo("Europe/Berlin")
    db = _db(tmp_path)
    record_heartbeat(db, "watchdog", now=datetime(2026, 8, 22, 19, 1, tzinfo=berlin).isoformat())
    gap = scheduler_gap(db, now=datetime(2026, 8, 23, 3, 30, tzinfo=berlin))

    assert gap["session_minutes"] == 0
    assert "kein Handelsschaden" in build_gap_text(gap)


def test_a_box_that_kept_running_reports_no_gap(tmp_path) -> None:
    from datetime import timedelta

    from equity_scout.watchdog import scheduler_gap

    db = _db(tmp_path)
    record_heartbeat(db, "watchdog", now=(NOW - timedelta(minutes=15)).isoformat())
    assert scheduler_gap(db, now=NOW) is None


def test_one_late_cycle_is_not_a_scheduler_outage(tmp_path) -> None:
    """A slow crypto fetch pushes the next run past its slot. Alarming on that would train
    the reader to ignore the alert — the threshold is three missed cycles."""
    from datetime import timedelta

    from equity_scout.watchdog import scheduler_gap

    db = _db(tmp_path)
    record_heartbeat(db, "watchdog", now=(NOW - timedelta(minutes=32)).isoformat())
    assert scheduler_gap(db, now=NOW) is None


def test_the_first_run_ever_reports_no_gap(tmp_path) -> None:
    """Same honesty rule as the chains: monitoring starts with the first heartbeat, not with
    an invented one."""
    from equity_scout.watchdog import scheduler_gap

    assert scheduler_gap(_db(tmp_path), now=NOW) is None


def test_the_cli_reports_the_gap_before_overwriting_the_heartbeat(tmp_path, monkeypatch) -> None:
    """The ordering IS the feature: writing the heartbeat first would measure a zero-length
    gap on every run, which is exactly why this outage class stayed invisible."""
    import json
    import sys
    from datetime import timedelta

    import scripts.run_watchdog as wd
    from equity_scout.state_storage import get_state
    from equity_scout.watchdog import LAST_GAP_KEY

    db = _db(tmp_path)
    record_heartbeat(db, "watchdog", now=(datetime.now(timezone.utc) -
                                          timedelta(hours=9)).isoformat())
    for var in ("COPILOT_TG_CHAT_ID_INTRADAY", "COPILOT_TG_CHAT_ID_DAILY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COPILOT_TG_BOT_TOKEN", "t")
    monkeypatch.setenv("COPILOT_TG_CHAT_ID", "1")
    sent: list[str] = []
    monkeypatch.setattr(wd, "send_message", lambda token, chat_id, text: sent.append(text) or 1)
    monkeypatch.setattr(sys, "argv", ["run_watchdog.py", "--db", db])

    assert wd.main() == 0
    assert any("Scheduler" in text for text in sent)
    assert json.loads(get_state(db, key=LAST_GAP_KEY))["hours"] > 8

    sent.clear()
    assert wd.main() == 0  # the predecessor is fresh now — never reported twice
    assert not any("Scheduler" in text for text in sent)


def test_a_recorded_divergence_is_reported(tmp_path) -> None:
    """The failure the heartbeat SLAs are blind to: every chain green, book and account apart."""
    from equity_scout.shortterm_storage import init_shortterm_db, set_lane_state
    from equity_scout.watchdog import position_divergence

    st_db = str(tmp_path / "st.db")
    init_shortterm_db(st_db)
    set_lane_state(st_db, "ignition", "broker_divergence", json.dumps(
        {"at": "2026-08-24T17:00:00+00:00",
         "items": [{"ticker": "MRVI", "book_qty": 128.0, "broker_qty": 424.0,
                    "kind": "broker_excess"}]}))
    found = position_divergence(st_db)
    assert found and found[0]["ticker"] == "MRVI"


def test_no_recorded_divergence_reports_nothing(tmp_path) -> None:
    from equity_scout.shortterm_storage import init_shortterm_db
    from equity_scout.watchdog import position_divergence

    st_db = str(tmp_path / "st.db")
    init_shortterm_db(st_db)
    assert position_divergence(st_db) == []


def test_an_unreadable_divergence_state_is_not_an_alarm(tmp_path) -> None:
    """A corrupt marker must not crash the dead-man — it is the one job that has to survive
    everything else being broken."""
    from equity_scout.shortterm_storage import init_shortterm_db, set_lane_state
    from equity_scout.watchdog import position_divergence

    st_db = str(tmp_path / "st.db")
    init_shortterm_db(st_db)
    set_lane_state(st_db, "ignition", "broker_divergence", "{nicht json")
    assert position_divergence(st_db) == []
