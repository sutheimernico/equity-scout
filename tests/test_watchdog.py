"""Dead-man watchdog (v12 W1): a silently dead chain must make noise — once per cooldown."""
from __future__ import annotations

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
