"""tests/test_chat_retrieval.py — deterministic retrieval in front of the LLM."""
from __future__ import annotations

from equity_scout.chat_retrieval import (
    candidate_symbols,
    find_persons,
    find_tickers,
    is_advice_question,
    metrics_lines,
    people_lines,
    route_topics,
    short_company_name,
    stock_dossier,
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


def test_lexicon_matching_ignores_generic_single_words():
    lex = {"FSTR": "First Company", "GLBL": "Global Group", "MU": "Micron Technology"}
    # "First"/"Global" allein sind Alltagswörter — sie dürfen keine Aktie treffen.
    assert find_tickers("Was ist global gerade wichtig?", lex) == []
    # Der VOLLE Name bleibt trotzdem auffindbar.
    assert find_tickers("Erste Frage zuerst: First Company?", lex) == ["FSTR"]
    assert find_tickers("Wie steht Micron?", lex) == ["MU"]


def test_symbol_match_requires_the_symbol_spelling():
    lex = {"ON": "ON Semiconductor", "ALL": "Allstate"}
    # "on"/"all" in Kleinschreibung sind Sprache, keine Ticker.
    assert find_tickers("Was ist on all das?", lex) == []
    assert find_tickers("Was macht ON gerade?", lex) == ["ON"]
    # Auch lange Buchstaben-Ticker treffen deutsche Wörter (SAGT, MEHR) — Kleinschreibung
    # zählt deshalb nie als Symbol-Nennung; der Firmenname bleibt der bequeme Weg.
    assert find_tickers("wie steht nvda?", {"NVDA": "NVIDIA"}) == []
    assert find_tickers("wie steht NVDA?", {"NVDA": "NVIDIA"}) == ["NVDA"]
    assert find_tickers("wie steht nvidia?", {"NVDA": "NVIDIA"}) == ["NVDA"]
    # Punktierte Symbole kann man nicht als Wort lesen — die dürfen klein bleiben.
    assert find_tickers("was macht itc.ns?", {"ITC.NS": "ITC"}) == ["ITC.NS"]


def test_german_question_words_never_resolve_to_a_stock():
    lex = {"WAS": "Wasion", "KURS": "Kurs Corp", "SAGT": "Sagtec Global", "MU": "Micron"}
    assert find_tickers("Was ist der Kurs von Micron?", lex) == ["MU"]
    # Live gegen das echte 6 197-Titel-Lexikon gefunden: "was sagt die Marktlage" ergab SAGT.
    assert find_tickers("Wie laufen die Depots und was sagt die Marktlage?", lex) == []


def test_stock_dossier_renders_every_known_fact():
    text = stock_dossier(
        ticker="ITC.NS",
        name="ITC",
        watchlist_entry={
            "composite": 0.71, "in_zone": True, "price": 286.95,
            "entry_zone_low": 276.11, "entry_zone_high": 319.50,
            "zone_note": "Kurs in der Einstiegszone (276.11–319.50).",
        },
        fundamentals=None,
        insight={"business": "ITC ist ein indischer Mischkonzern.",
                 "news_summary": "Quartalszahlen über Erwartung."},
        pitches=[{"status": "buy", "created_at": "2026-08-06T22:16:24+00:00",
                  "verdict": "green", "composite": 0.71}],
        evidence_events=[],
        held_by={"nico": 0.0, "autopilot": 12.5},
    )
    assert "ITC (ITC.NS)" in text
    assert "Einstiegs-Score 71/100" in text
    assert "in der Einstiegszone" in text
    assert "Mischkonzern" in text
    assert "Pitch vom 2026-08-06" in text and "Gekauft" in text
    assert "Autopilot-Depot" in text  # hält 12.5 Anteile


def test_stock_dossier_says_whats_missing_instead_of_omitting():
    text = stock_dossier(
        ticker="MU", name="Micron Technology", watchlist_entry=None,
        fundamentals=None, insight=None, pitches=[], evidence_events=[], held_by={},
    )
    assert "NICHT auf der aktuellen Watchlist" in text
    assert "Keine Analysten-Daten im Cache" in text


def test_metrics_lines_render_every_cached_number_with_its_unit():
    text = "\n".join(metrics_lines({
        "trailing_pe": 22.3, "price_to_book": 5.42, "return_on_equity": 0.3056,
        "profit_margins": 0.1744, "revenue_growth": 0.196, "earnings_growth": 2.423,
        "momentum_6m": 0.2458, "volatility_6m": 0.0241, "price": 277.42,
        "high_52w_proximity": 0.987,
    }, fetched_on="2026-08-04"))
    assert "KGV 22,3" in text
    assert "Kurs-Buchwert-Verhältnis 5,4" in text
    assert "Eigenkapitalrendite 30,6 %" in text
    assert "Nettomarge 17,4 %" in text
    assert "Umsatzwachstum +19,6 %" in text
    assert "Gewinnwachstum +242,3 %" in text
    assert "6-Monats-Rendite +24,6 %" in text
    assert "Tagesschwankung 2,4 %" in text
    assert "99 % seines 52-Wochen-Hochs" in text
    assert "Stand 2026-08-04" in text


def test_metrics_lines_name_the_gaps_instead_of_dropping_them():
    text = "\n".join(metrics_lines({"trailing_pe": None, "price": 12.0},
                                   fetched_on="2026-08-04"))
    assert "Ohne Wert im Cache: KGV" in text


def test_negative_pe_is_explained_not_hidden():
    # Ein negatives KGV heißt Verlust — verschweigen wäre die gefährlichere Variante.
    text = "\n".join(metrics_lines({"trailing_pe": -12.4}, fetched_on="2026-08-04"))
    assert "KGV -12,4" in text and "Verlust" in text


def test_dossier_carries_metrics_factors_fscore_and_earnings():
    from equity_scout.fundamentals import Fundamentals

    text = stock_dossier(
        ticker="MU", name="Micron Technology", watchlist_entry=None,
        fundamentals=Fundamentals(trailing_pe=22.3, analyst_target=180.0, analyst_count=31,
                                  currency="USD", sector="Technology",
                                  industry="Semiconductors", year_high=190.0),
        insight=None, pitches=[], evidence_events=[], held_by={},
        metrics={"trailing_pe": 22.3, "price": 160.0}, metrics_fetched_on="2026-08-04",
        factor_breakdown={"value": 0.87, "quality": 0.42, "momentum": 0.61,
                          "growth": 0.55, "low_vol": 0.30},
        fscore={"score": 7, "evaluable": 9, "fiscal_year": 2025},
        next_earnings="2026-09-24",
    )
    assert "Technology / Semiconductors" in text
    assert "KGV 22,3" in text
    assert "Substanz-Bewertung 87/100" in text        # value-Perzentil im Sektorvergleich
    assert "Bilanz-Trend (F-Score) 7 von 9" in text
    assert "Nächster Termin: Quartalszahlen am 2026-09-24" in text
    assert "52-Wochen-Hoch 190.0" in text


def test_candidate_symbols_finds_an_unknown_ticker():
    assert candidate_symbols("Was ist das KGV von RHM.DE?", known={"MU"}) == ["RHM.DE"]
    assert candidate_symbols("Wie steht TSLA gerade?", known={"MU"}) == ["TSLA"]


def test_candidate_symbols_ignores_finance_abbreviations_and_known_tickers():
    # "KGV"/"ETF"/"USD" sind Vokabular, keine Ticker — ein Lookup darauf wäre Unsinn.
    assert candidate_symbols("Was sagt das KGV in USD über den ETF?", known=set()) == []
    # Bereits im Lexikon gefundene Ticker brauchen keinen Live-Nachschlag.
    assert candidate_symbols("Wie steht MU?", known={"MU"}) == []
    # Kleinschreibung ist Sprache, kein Symbol.
    assert candidate_symbols("was ist mit rheinmetall?", known=set()) == []


def test_routing_picks_depot_block_for_depot_questions():
    assert "depots" in route_topics("Wie steht mein Auto-Depot im Vergleich zum Markt?")


def test_routing_picks_people_for_person_questions():
    assert "personen" in route_topics("Was hat Warren Buffett zuletzt gekauft?")
    assert "personen" in route_topics("Welche Mitglieder haben Intel gekauft?")


def test_routing_defaults_to_overview_when_nothing_matches():
    assert route_topics("Wie geht es dir?") == ["ueberblick"]


def test_routing_can_return_multiple_topics():
    topics = route_topics("Wie laufen die Depots und was sagt die Marktlage?")
    assert "depots" in topics and "markt" in topics


def test_routing_picks_kennzahlen_for_metric_questions():
    for q in ("Wie hoch ist das KGV von Micron?", "Zeig mir die Kennzahlen",
              "Wie ist die Marge?", "Was ist die Bewertung wert?"):
        assert "kennzahlen" in route_topics(q), q


CONGRESS_EVENT = {
    "source": "congress", "event_date": "2026-08-05",
    "details": {"politician": "Thomas H Tuberville", "party": "R", "chamber": "senate",
                "transaction_date": "2024-05-07", "filing_date": "2026-08-05",
                "amount_range": "$100,001 - $250,000", "days_to_file": 820},
}


def test_people_lines_name_names_party_amount_and_reporting_lag():
    line = "\n".join(people_lines([CONGRESS_EVENT]))
    assert "Thomas H Tuberville" in line and "Senat" in line and "R" in line
    assert "$100,001 - $250,000" in line
    assert "gekauft am 2024-05-07" in line and "gemeldet 2026-08-05" in line
    # Der Meldeverzug ist die Nachricht, nicht die Fußnote: 820 Tage alte "News".
    assert "820 Tage" in line


def test_people_lines_render_funds_voices_and_filings():
    text = "\n".join(people_lines([
        {"source": "thirteen_f", "event_date": "2026-05-15",
         "details": {"fund": "Himalaya Capital", "period": "2026-03-31",
                     "filed_at": "2026-05-15", "change": "new", "shares": 6590836.0}},
        {"source": "voice", "event_date": "2026-08-06",
         "details": {"speaker": "Michael Burry", "kind": "context",
                     "headline": "Michael Burry Warns Of A 1987-Type Crash"}},
        {"source": "edgar_8k", "event_date": "2026-08-05",
         "details": {"items": ["2.02"], "filing_date": "2026-08-05"}},
    ]))
    assert "Himalaya Capital" in text and "neue Position" in text
    assert "Michael Burry" in text and "Erwähnung" in text
    assert "Quartalszahlen" in text  # 8-K Item 2.02 in Klartext


def test_people_lines_say_when_there_is_nothing():
    assert people_lines([]) == ["- Keine gemeldeten Käufe oder Stimmen zu diesem Titel."]


def test_find_persons_matches_full_names_and_unique_surnames():
    names = ["Thomas H Tuberville", "Warren Buffett", "Michael Burry"]
    assert find_persons("Was hat Tuberville zuletzt gekauft?", names) == ["Thomas H Tuberville"]
    assert find_persons("Was kauft Warren Buffett?", names) == ["Warren Buffett"]
    assert find_persons("Wie ist die Marktlage?", names) == []


def test_find_persons_skips_ambiguous_surnames():
    names = ["Michael Burry", "Steven Burry"]
    # "Burry" allein ist mehrdeutig — dann lieber kein Treffer als der falsche.
    assert find_persons("Was macht Burry?", names) == []
    assert find_persons("Was macht Michael Burry?", names) == ["Michael Burry"]
