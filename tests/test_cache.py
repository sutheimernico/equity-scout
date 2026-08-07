from equity_scout.data.cache import CachedProvider, QuoteCache, is_fresh
from equity_scout.data.fake_provider import FakeProvider
from equity_scout.models import Instrument

INST = Instrument("AAPL", "Apple", "NASDAQ", "US", "USD", "Tech")


class CountingProvider:
    """Wraps a provider, counts fetch calls — to prove the cache avoids re-fetching."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def fetch_quote(self, instrument):
        self.calls += 1
        return self.inner.fetch_quote(instrument)


def _inner():
    return CountingProvider(FakeProvider({"AAPL": dict(trailing_pe=10.0, momentum_6m=0.1)}))


def test_cache_miss_then_hit_avoids_second_fetch(tmp_path):
    inner = _inner()
    prov = CachedProvider(inner, QuoteCache(tmp_path / "c.db"), run_date="2026-06-24")
    q1 = prov.fetch_quote(INST)
    q2 = prov.fetch_quote(INST)
    assert inner.calls == 1
    assert q1.trailing_pe == q2.trailing_pe == 10.0


def test_cache_stale_triggers_refetch(tmp_path):
    inner = _inner()
    cache = QuoteCache(tmp_path / "c.db")
    cache.put("AAPL", dict(trailing_pe=99.0, price_to_book=None, return_on_equity=None,
                           profit_margins=None, revenue_growth=None, earnings_growth=None,
                           momentum_6m=0.1), fetched_on="2020-01-01")
    prov = CachedProvider(inner, cache, run_date="2026-06-24", max_age_days=1)
    q = prov.fetch_quote(INST)
    assert inner.calls == 1  # stale -> refetched
    assert q.trailing_pe == 10.0  # fresh value, not the stale 99.0


def test_is_fresh_boundaries():
    assert is_fresh("2026-06-24", "2026-06-24", 1) is True
    assert is_fresh("2026-06-23", "2026-06-24", 1) is True
    assert is_fresh("2026-06-22", "2026-06-24", 1) is False


def test_load_cached_metrics_batches_and_tolerates_a_missing_cache(tmp_path):
    from equity_scout.data.cache import load_cached_metrics

    db = tmp_path / "cache.db"
    cache = QuoteCache(db)
    cache.put("MU", {"trailing_pe": 22.3, "price": 160.0}, "2026-08-04")
    cache.put("INTC", {"trailing_pe": None, "price": 24.0}, "2026-08-05")

    hits = load_cached_metrics(db, ["MU", "INTC", "NOPE"])
    assert hits["MU"] == ("2026-08-04", {"trailing_pe": 22.3, "price": 160.0})
    assert hits["INTC"][0] == "2026-08-05"
    assert "NOPE" not in hits
    # Eine fehlende Cache-Datei ist ein normaler Zustand, kein Fehler im Chat-Pfad.
    assert load_cached_metrics(tmp_path / "absent.db", ["MU"]) == {}
    assert load_cached_metrics(db, []) == {}
