"""tests/test_chat_retrieval.py — deterministic retrieval in front of the LLM."""
from __future__ import annotations

from equity_scout.chat_retrieval import (
    find_tickers,
    is_advice_question,
    short_company_name,
)


def test_advice_questions_are_detected():
    for q in [
        "Soll ich Micron kaufen?",
        "soll ich jetzt bei ITC einsteigen",
        "Würdest du Yamato verkaufen?",
        "Lohnt es sich, Petrobras zu kaufen?",
        "Was soll ich kaufen?",
    ]:
        assert is_advice_question(q), q


def test_data_questions_are_not_advice():
    for q in [
        "Was macht Micron und warum ist die Aktie im Radar?",
        "Wie steht mein Auto-Depot im Vergleich zum Markt?",
        "Was bedeutet die Einstiegszone?",
        "Wer hat zuletzt Intel gekauft?",  # Frage über KÄUFE Dritter, kein Rat
    ]:
        assert not is_advice_question(q), q


LEXICON = {
    "MU": "Micron Technology",
    "ITC.NS": "ITC",
    "9064.T": "Yamato Holdings Co., Ltd.",
    "PETR4.SA": "Petrobras",
    "INTC": "Intel",
    "V": "Visa",
}


def test_finds_ticker_by_company_name_case_insensitive():
    assert find_tickers("was macht micron gerade?", LEXICON) == ["MU"]


def test_finds_ticker_by_symbol():
    assert find_tickers("Warum ist ITC.NS im Radar?", LEXICON) == ["ITC.NS"]


def test_short_names_need_word_boundaries():
    # "ITC" steckt in "pitches" — ohne Wortgrenzen wäre jede Frage ein ITC-Treffer.
    assert find_tickers("Wie viele Pitches sind offen?", LEXICON) == []
    # Einbuchstabige Ticker (V) matchen NIE über den Namen hinaus.
    assert find_tickers("Was sagen die Analysten zu Visa?", LEXICON) == ["V"]
    assert find_tickers("Vielleicht später", LEXICON) == []


def test_multiple_mentions_keep_question_order_and_dedupe():
    q = "Vergleiche Micron mit Intel und nochmal Micron"
    assert find_tickers(q, LEXICON) == ["MU", "INTC"]


def test_company_suffixes_do_not_block_the_match():
    # Lexikon-Name "Yamato Holdings Co., Ltd." muss über "Yamato" gefunden werden —
    # dafür wird der Name mit company.shortCompanyName-Logik serverseitig gekürzt.
    assert find_tickers("Warum wurde Yamato nicht gekauft?", LEXICON) == ["9064.T"]


def test_longest_name_wins_over_a_shorter_one():
    lex = {"AAA": "Alpha", "BBB": "Alpha Beta Systems"}
    assert find_tickers("Was macht Alpha Beta Systems?", lex) == ["BBB"]


def test_suffix_strip_only_eats_whole_words():
    # Ohne Wortgrenze verlor "Visa" seinen Namen an das `s.a.`-Suffix und "Cisco" an `co`
    # — beide waren damit für den Assistenten unauffindbar.
    assert short_company_name("Visa Inc.") == "Visa"
    assert short_company_name("Cisco Systems, Inc.") == "Cisco Systems"
    assert short_company_name("Yamato Holdings Co., Ltd.") == "Yamato"
