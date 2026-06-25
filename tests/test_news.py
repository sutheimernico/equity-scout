from equity_scout.data.news import FakeNews, attach_news, parse_news
from equity_scout.models import Instrument, Pick


def _pick(ticker, rank):
    inst = Instrument(ticker, ticker, "E", "US", "USD", "Tech")
    return Pick(inst, "balanced", rank, 0.8, {"value": 0.5, "quality": 0.5, "momentum": 0.5})


def test_parse_news_normalises_nested_yahoo_schema():
    raw = [{
        "id": "1",
        "content": {
            "title": "Big news",
            "provider": {"displayName": "Reuters"},
            "pubDate": "2026-06-24T15:00:00Z",
            "canonicalUrl": {"url": "http://x"},
        },
    }]
    assert parse_news(raw) == [
        {"title": "Big news", "publisher": "Reuters", "published": "2026-06-24", "link": "http://x"}
    ]


def test_parse_news_respects_limit_and_skips_untitled():
    raw = [{"content": {"title": f"n{i}"}} for i in range(5)] + [{"content": {}}]
    out = parse_news(raw, limit=2)
    assert [item["title"] for item in out] == ["n0", "n1"]


def test_parse_news_handles_empty():
    assert parse_news(None) == []
    assert parse_news([]) == []


def test_attach_news_only_top_n_picks():
    buckets = {"balanced": [_pick("AAA", 1), _pick("BBB", 2), _pick("CCC", 3)]}
    provider = FakeNews({"AAA": [{"title": "a"}], "BBB": [{"title": "b"}], "CCC": [{"title": "c"}]})
    out = attach_news(buckets, provider, max_per_bucket=2)
    assert out["balanced"][0].news == [{"title": "a"}]  # rank 1
    assert out["balanced"][1].news == [{"title": "b"}]  # rank 2
    assert out["balanced"][2].news == []  # rank 3 > cap → no fetch


def test_attach_news_none_provider_is_unchanged():
    buckets = {"balanced": [_pick("AAA", 1)]}
    assert attach_news(buckets, None) == buckets
