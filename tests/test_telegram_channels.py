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


def test_build_multipart_encodes_fields_and_file():
    from equity_scout.telegram_client import build_multipart

    body, content_type = build_multipart(
        {"chat_id": "42", "caption": "hällo"}, "photo", "chart.png",
        b"\x89PNG\r\n\x1a\nDATA", "BOUND"
    )
    assert content_type == "multipart/form-data; boundary=BOUND"
    assert b'name="chat_id"\r\n\r\n42' in body
    assert "hällo".encode("utf-8") in body
    assert b'filename="chart.png"' in body
    assert b"Content-Type: image/png" in body
    assert body.endswith(b"--BOUND--\r\n")
    assert b"\x89PNG" in body


def test_edit_pitch_outcome_text_message_direct():
    from equity_scout.telegram_client import edit_pitch_outcome

    calls: list = []
    edit_pitch_outcome(lambda m, t: calls.append(("text", m, t)),
                       lambda m, c: calls.append(("caption", m, c)), 7, "Pitch\n— Entscheidung: ✅")
    assert calls == [("text", 7, "Pitch\n— Entscheidung: ✅")]


def test_edit_pitch_outcome_falls_back_to_caption_for_photos():
    from equity_scout.telegram_client import TelegramError, edit_pitch_outcome

    def no_text(_m, _t):
        raise TelegramError("Bad Request: there is no text in the message to edit")

    calls: list = []
    edit_pitch_outcome(no_text, lambda m, c: calls.append((m, c)), 7,
                       "📈 NVDA — NVIDIA\nlange Zeile\n— Entscheidung: ✅ Kaufen")
    assert calls == [(7, "📈 NVDA — NVIDIA\n— Entscheidung: ✅ Kaufen")]


def test_edit_pitch_outcome_not_modified_counts_as_success():
    from equity_scout.telegram_client import TelegramError, edit_pitch_outcome

    def unchanged(_m, _t):
        raise TelegramError("Bad Request: message is not modified")

    calls: list = []
    edit_pitch_outcome(unchanged, lambda m, c: calls.append((m, c)), 7, "x\ny")
    assert calls == []
