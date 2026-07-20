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


def _tg_env(monkeypatch):
    for var in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO",
                "COPILOT_TG_CHAT_ID_INTRADAY", "COPILOT_TG_CHAT_ID_DAILY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("COPILOT_TG_BOT_TOKEN", "test-token")
    monkeypatch.setenv("COPILOT_TG_CHAT_ID", "123456")


def test_telegram_failure_stores_pending_and_next_chain_run_resends(tmp_path, monkeypatch):
    """R6/P1 (review 2026-07-20): one network blip at 18:05 must not kill the day's
    digest — it is persisted and resent by the next chain run, exactly once."""
    from equity_scout.telegram_client import TelegramError
    from scripts.run_digest import maybe_resend_pending

    db = str(tmp_path / "inbox.db")
    _tg_env(monkeypatch)

    def broken_send(token, chat_id, text, parse_mode=None):
        raise TelegramError("network down")

    monkeypatch.setattr(run_digest, "send_long_message", broken_send)
    monkeypatch.setattr(sys, "argv", ["run_digest.py", "--db", db])
    today = datetime.now(timezone.utc).date().isoformat()

    assert main() == 0  # guard semantics unchanged: chain must not die
    assert get_state(db, key="digest_sent_on") is None
    assert get_state(db, key="digest_pending_date") == today
    assert get_state(db, key="digest_pending_text")

    sent: list[str] = []
    monkeypatch.setattr(
        run_digest, "send_long_message",
        lambda token, chat_id, text, parse_mode=None: sent.append(text) or 1,
    )
    assert maybe_resend_pending(db) is True
    assert len(sent) == 1
    assert get_state(db, key="digest_sent_on") == today
    assert get_state(db, key="digest_pending_date") == ""
    assert maybe_resend_pending(db) is False  # cleared — never sent twice
    assert len(sent) == 1


def test_stale_pending_from_yesterday_is_dropped_not_sent(tmp_path, monkeypatch):
    from equity_scout.state_storage import set_state
    from scripts.run_digest import maybe_resend_pending

    db = str(tmp_path / "inbox.db")
    _tg_env(monkeypatch)
    set_state(db, key="digest_pending_date", value="2026-07-19")
    set_state(db, key="digest_pending_text", value="<b>alt</b>")

    sent: list[str] = []
    monkeypatch.setattr(
        run_digest, "send_long_message",
        lambda token, chat_id, text, parse_mode=None: sent.append(text) or 1,
    )
    assert maybe_resend_pending(db) is False
    assert sent == []
    assert get_state(db, key="digest_pending_date") == ""


def test_digest_run_records_daily_heartbeat(tmp_path, monkeypatch):
    db = str(tmp_path / "inbox.db")
    for var in ("SMTP_HOST", "COPILOT_TG_BOT_TOKEN", "COPILOT_TG_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "argv", ["run_digest.py", "--db", db])
    assert main() == 0  # unconfigured stdout run still proves the chain is alive
    assert get_state(db, key="heartbeat_daily") is not None


def test_dash_url_footer_appears_once_per_week(tmp_path, monkeypatch):
    db = str(tmp_path / "inbox.db")
    _tg_env(monkeypatch)
    monkeypatch.setenv("DASH_URL", "http://192.168.1.20:8420/?token=x")
    sent: list[str] = []
    monkeypatch.setattr(
        run_digest, "send_long_message",
        lambda token, chat_id, text, parse_mode=None: sent.append(text) or 1,
    )
    monkeypatch.setattr(sys, "argv", ["run_digest.py", "--db", db])

    assert main() == 0
    assert "📱 Dashboard (Heimnetz)" in sent[0]
    assert get_state(db, key="dash_url_hint_week") is not None

    monkeypatch.setattr(sys, "argv", ["run_digest.py", "--db", db, "--force"])
    assert main() == 0  # same week, forced re-send -> no repeated hint
    assert "📱 Dashboard" not in sent[1]
