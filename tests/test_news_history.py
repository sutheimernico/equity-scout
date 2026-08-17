"""Historical news store: second-level stamps, exact symbol matching, honest gaps."""

from equity_scout.data.news_history import (
    items_for_ticker,
    load_news,
    news_path,
    parse_news_page,
    save_year,
)

PAGE = {
    "news": [
        {"created_at": "2016-01-04T11:15:03Z", "symbols": ["AAPL", "MSFT"],
         "headline": "Traders Are Bullish", "source": "benzinga"},
        {"created_at": "2016-01-04T11:20:00Z", "symbols": ["V"],
         "headline": "Visa moves", "source": "benzinga"},
        {"created_at": None, "symbols": ["GLD"], "headline": "no stamp"},
        {"created_at": "2016-01-04T12:00:00Z", "symbols": ["GLD"], "headline": None},
    ],
    "next_page_token": "next",
}


def test_parse_keeps_second_resolution_and_drops_unusable_items():
    frame, token = parse_news_page(PAGE)
    assert token == "next"
    assert len(frame) == 2  # the stampless and headline-less items are gone
    assert str(frame["created_at"].iloc[0]) == "2016-01-04 11:15:03+00:00"
    assert frame["symbols"].iloc[0] == "AAPL,MSFT"


def test_parse_empty_payload_is_empty_not_error():
    frame, token = parse_news_page({})
    assert frame.empty and token is None


def test_symbol_matching_is_exact_not_substring():
    frame, _ = parse_news_page(PAGE)
    # 'V' must not match the item tagged AAPL,MSFT — and must match its own
    assert len(items_for_ticker(frame, "V")) == 1
    assert items_for_ticker(frame, "V")["headline"].iloc[0] == "Visa moves"
    assert len(items_for_ticker(frame, "AAPL")) == 1
    assert len(items_for_ticker(frame, "NVDA")) == 0


def test_save_and_load_roundtrip_keeps_utc(tmp_path):
    frame, _ = parse_news_page(PAGE)
    save_year(frame, 2016, root=tmp_path)
    assert news_path(2016, root=tmp_path).exists()
    back = load_news([2016], root=tmp_path)
    assert len(back) == 2
    assert str(back["created_at"].dt.tz) == "UTC"


def test_load_missing_year_is_empty(tmp_path):
    assert load_news([2016], root=tmp_path).empty
