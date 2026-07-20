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
