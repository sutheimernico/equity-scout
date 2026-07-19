from scripts.run_digest import should_skip_send


def test_skips_when_already_sent_today_and_configured():
    assert should_skip_send("2026-07-19", today="2026-07-19", force=False, configured=True)


def test_never_skips_with_force():
    assert not should_skip_send("2026-07-19", today="2026-07-19", force=True, configured=True)


def test_never_skips_unconfigured_stdout_runs():
    assert not should_skip_send("2026-07-19", today="2026-07-19", force=False, configured=False)


def test_runs_when_not_yet_sent():
    assert not should_skip_send(None, today="2026-07-19", force=False, configured=True)
    assert not should_skip_send("2026-07-18", today="2026-07-19", force=False, configured=True)
