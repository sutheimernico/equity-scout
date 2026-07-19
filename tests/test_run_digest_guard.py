import sys
from datetime import datetime, timezone

import scripts.run_digest as run_digest
from equity_scout.state_storage import get_state
from scripts.run_digest import main, should_skip_send


def test_skips_when_already_sent_today_and_configured():
    assert should_skip_send("2026-07-19", today="2026-07-19", force=False, configured=True)


def test_never_skips_with_force():
    assert not should_skip_send("2026-07-19", today="2026-07-19", force=True, configured=True)


def test_never_skips_unconfigured_stdout_runs():
    assert not should_skip_send("2026-07-19", today="2026-07-19", force=False, configured=False)


def test_runs_when_not_yet_sent():
    assert not should_skip_send(None, today="2026-07-19", force=False, configured=True)
    assert not should_skip_send("2026-07-18", today="2026-07-19", force=False, configured=True)


def test_main_sets_marker_on_send_and_skips_second_same_day_call(tmp_path, monkeypatch):
    """Integration test for the main() wiring: a configured run marks the day sent, and
    a second same-day call must not touch the (faked) Telegram transport again."""
    from equity_scout.inbox_storage import create_pitch

    db = str(tmp_path / "inbox.db")
    create_pitch(
        db, ticker="EXE", watchlist_id=1, price=90.72, composite=0.59,
        zone_low=85.0, zone_high=95.0, pitch="Pitch", created_at="2026-07-05T10:00:00+00:00",
    )
    for var in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO",
                "COPILOT_TG_CHAT_ID_INTRADAY", "COPILOT_TG_CHAT_ID_DAILY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COPILOT_TG_BOT_TOKEN", "test-token")
    monkeypatch.setenv("COPILOT_TG_CHAT_ID", "123456")

    sent: list[tuple] = []

    def fake_send_long_message(token, chat_id, text, parse_mode=None):
        sent.append((token, chat_id, parse_mode))
        return 1

    monkeypatch.setattr(run_digest, "send_long_message", fake_send_long_message)
    monkeypatch.setattr(sys, "argv", ["run_digest.py", "--db", db])

    today = datetime.now(timezone.utc).date().isoformat()

    assert main() == 0
    assert len(sent) == 1
    assert get_state(db, key="digest_sent_on") == today

    # Second call, same day: the guard must skip before the (faked) send is reached.
    assert main() == 0
    assert len(sent) == 1
