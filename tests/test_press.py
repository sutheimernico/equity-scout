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
    assert clean_company_query("SAP SE") == "SAP"
    assert clean_company_query("Plain Name") == "Plain Name"


def test_clean_company_query_strips_exchange_listing_descriptions():
    """Nasdaq-sourced watchlist names carry the listing type, which is not part of any
    news headline. Measured 2026-08-05: with it in the phrase, 4 of the top 12 watchlist
    stocks found ZERO headlines (INSW, SHIP, AIRT, CMBT)."""
    assert clean_company_query("Dorian LPG Ltd. Common Stock") == "Dorian LPG"
    assert clean_company_query("Air T, Inc. - Common Stock") == "Air T"
    assert clean_company_query("International Seaways, Inc. Common Stock") == (
        "International Seaways"
    )
    assert clean_company_query("CMB.TECH NV Ordinary Shares") == "CMB.TECH"
    assert clean_company_query("Carter Bankshares, Inc. - Common Stock") == "Carter Bankshares"


def test_clean_company_query_keeps_holdings_when_it_carries_the_name():
    """"Holdings"/"Group" is a name part, not a legal form — dropping it can turn a
    specific company into a family name several listed firms share.

    Measured 2026-08-05: "Yamato Holdings Co., Ltd." (9064.T) reduced to "Yamato" and the
    resulting summary described TSE:1967, TSE:5444 and TSE:8127 — three other companies.
    This test previously asserted "X Holdings Inc." -> "X", which is the same defect in
    miniature.
    """
    assert clean_company_query("Yamato Holdings Co., Ltd.") == "Yamato Holdings"
    assert clean_company_query("X Holdings Inc.") == "X Holdings"
    # With two words still left, the noise word goes: a legal form after it is stripped
    # first, so the check runs against what would remain.
    assert clean_company_query("Seanergy Maritime Holdings Corp. - Common Stock") == (
        "Seanergy Maritime"
    )


def test_clean_company_query_leaves_a_genuinely_single_word_name_alone():
    assert clean_company_query("Petrobras") == "Petrobras"
    assert clean_company_query("Tele2") == "Tele2"


def test_fetch_press_lines_returns_truncated_titles():
    lines = fetch_press_lines("Toyota Motor Corp.", http_get=lambda url: _FEED)
    assert len(lines) == 2
    assert lines[0] == "Toyota bets big on solid-state batteries"
    assert len(lines[1]) <= 90 and lines[1].endswith("…")


def test_fetch_press_lines_swallows_transport_errors():
    def boom(url: str) -> str:
        raise OSError("offline")

    assert fetch_press_lines("Toyota", http_get=boom) == []
