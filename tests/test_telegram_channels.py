"""Channel routing config (intraday/daily chat ids with fallback) + message chunking."""
from equity_scout.telegram_client import load_telegram_config, split_message

BASE_ENV = {"COPILOT_TG_BOT_TOKEN": "t0k", "COPILOT_TG_CHAT_ID": "111"}


def test_channel_ids_fall_back_to_main_chat():
    config = load_telegram_config(dict(BASE_ENV))
    assert config == {"token": "t0k", "chat_id": 111,
                      "intraday_chat_id": 111, "daily_chat_id": 111}


def test_channel_ids_used_when_set():
    env = dict(BASE_ENV, COPILOT_TG_CHAT_ID_INTRADAY="-222", COPILOT_TG_CHAT_ID_DAILY="-333")
    config = load_telegram_config(env)
    assert config["intraday_chat_id"] == -222
    assert config["daily_chat_id"] == -333
    assert config["chat_id"] == 111


def test_malformed_channel_id_falls_back(capsys):
    env = dict(BASE_ENV, COPILOT_TG_CHAT_ID_INTRADAY="not-a-number")
    config = load_telegram_config(env)
    assert config["intraday_chat_id"] == 111
    assert "COPILOT_TG_CHAT_ID_INTRADAY" in capsys.readouterr().err


def test_missing_main_config_still_disables_everything():
    assert load_telegram_config({"COPILOT_TG_CHAT_ID_INTRADAY": "-222"}) is None


def test_split_message_short_text_is_single_chunk():
    assert split_message("hallo", limit=100) == ["hallo"]


def test_split_message_splits_at_line_boundaries():
    text = "\n".join(f"zeile {i}" for i in range(10))
    chunks = split_message(text, limit=30)
    assert all(len(c) <= 30 for c in chunks)
    assert "\n".join(chunks) == text  # nothing lost, order kept


def test_split_message_hard_splits_single_overlong_line():
    text = "x" * 95
    chunks = split_message(text, limit=40)
    assert all(len(c) <= 40 for c in chunks)
    assert "".join(chunks) == text
