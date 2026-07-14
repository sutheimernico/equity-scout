import pytest

from equity_scout.data.fake_provider import FakeProvider
from equity_scout.data.fetch import fetch_all, retry_delays, with_retry
from equity_scout.models import Instrument


def test_retry_delays_exponential_with_cap():
    assert retry_delays(3, base=0.5, cap=8.0) == [0.5, 1.0]
    assert retry_delays(5, base=1.0, cap=4.0) == [1.0, 2.0, 4.0, 4.0]
    assert retry_delays(1) == []


def test_with_retry_succeeds_after_transient_failures():
    calls = {"n": 0}
    slept: list[float] = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    result = with_retry(flaky, attempts=3, sleep=slept.append)
    assert result == "ok"
    assert calls["n"] == 3
    assert slept == [0.5, 1.0]


def test_with_retry_reraises_after_exhaustion():
    def always_fails():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        with_retry(always_fails, attempts=2, sleep=lambda _: None)


def test_with_retry_logs_each_failed_attempt(caplog):
    # The broad except used to fail silently; every attempt must now be visible in the logs.
    def always_fails():
        raise ValueError("nope")

    with caplog.at_level("WARNING"):
        with pytest.raises(ValueError):
            with_retry(always_fails, attempts=3, sleep=lambda _: None)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 3
    assert all("attempt" in r.message for r in warnings)


def test_fetch_all_preserves_order_parallel_and_serial():
    universe = [Instrument(t, t, "US", "US", "USD", "Tech") for t in ("A", "B", "C")]
    provider = FakeProvider({t: dict(trailing_pe=float(i)) for i, t in enumerate(("A", "B", "C"))})
    serial = fetch_all(provider, universe, max_workers=1)
    parallel = fetch_all(provider, universe, max_workers=4)
    assert [q.instrument.ticker for q in serial] == ["A", "B", "C"]
    assert [q.instrument.ticker for q in parallel] == ["A", "B", "C"]


def test_with_retry_uses_long_backoff_for_rate_limit_errors():
    from equity_scout.data.fetch import with_retry

    class YFRateLimitError(Exception):
        pass

    sleeps: list[float] = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise YFRateLimitError("Too Many Requests")
        return "ok"

    result = with_retry(flaky, attempts=3, rate_limit_base=30.0, sleep=sleeps.append)
    assert result == "ok"
    assert sleeps == [30.0, 60.0]  # 30s * 2^i, not the sub-second default backoff


def test_with_retry_keeps_short_backoff_for_ordinary_errors():
    from equity_scout.data.fetch import with_retry

    sleeps: list[float] = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise OSError("transient")
        return "ok"

    assert with_retry(flaky, attempts=3, base=0.5, cap=8.0, sleep=sleeps.append) == "ok"
    assert sleeps and sleeps[0] < 30.0
