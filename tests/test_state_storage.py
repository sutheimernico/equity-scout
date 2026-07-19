from equity_scout.state_storage import get_state, set_state


def test_get_state_missing_key_returns_none(tmp_path):
    db = str(tmp_path / "t.db")
    assert get_state(db, key="nope") is None


def test_set_then_get_roundtrip(tmp_path):
    db = str(tmp_path / "t.db")
    set_state(db, key="digest_sent_on", value="2026-07-19")
    assert get_state(db, key="digest_sent_on") == "2026-07-19"


def test_set_overwrites(tmp_path):
    db = str(tmp_path / "t.db")
    set_state(db, key="k", value="a")
    set_state(db, key="k", value="b")
    assert get_state(db, key="k") == "b"
