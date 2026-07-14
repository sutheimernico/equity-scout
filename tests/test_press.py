"""Press voices: clean company query + headline fetch through an injected transport."""
from equity_scout.press import clean_company_query, fetch_press_lines

_FEED = """<rss><channel>
<item><title>Toyota bets big on solid-state batteries</title><pubDate>x</pubDate></item>
<item><title>Why Toyota's hybrid lead keeps growing — a very long headline that easily
exceeds the ninety character caption budget for a single line</title><pubDate>x</pubDate></item>
<item><title>Third headline that should be cut by the limit</title><pubDate>x</pubDate></item>
</channel></rss>"""


def test_clean_company_query_strips_legal_suffixes():
    assert clean_company_query("NVIDIA Corp.") == "NVIDIA"
    assert clean_company_query("Toyota Motor Corporation") == "Toyota Motor"
    assert clean_company_query("X Holdings Inc.") == "X"
    assert clean_company_query("SAP SE") == "SAP"
    assert clean_company_query("Plain Name") == "Plain Name"


def test_fetch_press_lines_returns_truncated_titles():
    lines = fetch_press_lines("Toyota Motor Corp.", http_get=lambda url: _FEED)
    assert len(lines) == 2
    assert lines[0] == "Toyota bets big on solid-state batteries"
    assert len(lines[1]) <= 90 and lines[1].endswith("…")


def test_fetch_press_lines_swallows_transport_errors():
    def boom(url: str) -> str:
        raise OSError("offline")

    assert fetch_press_lines("Toyota", http_get=boom) == []
