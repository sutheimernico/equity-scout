"""German evidence surfaces: pitch block, alert selection, alert text.

Every surface must carry the structural-delay honesty note; alerts must be
unmistakably labelled as NOT coming from the screener (no score, no buttons).
"""
from __future__ import annotations

from equity_scout.evidence.aggregate import (
    DELAY_NOTE,
    build_alert_text,
    distinct_buyer_count,
    evidence_block,
    select_evidence_alerts,
)
from equity_scout.evidence.base import (
    SOURCE_8K,
    SOURCE_13F,
    SOURCE_CONGRESS,
    SOURCE_INSIDER,
    SOURCE_NEWS_THEME,
)


def _congress(ticker: str, politician: str, filing_date: str = "2026-07-01") -> dict:
    return {
        "source": SOURCE_CONGRESS,
        "ticker": ticker,
        "event_key": f"{politician}-{filing_date}",
        "event_date": filing_date,
        "details": {"politician": politician, "filing_date": filing_date},
    }


def _fund(ticker: str, fund: str, change: str = "new") -> dict:
    return {
        "source": SOURCE_13F,
        "ticker": ticker,
        "event_key": f"{fund}-2026Q2",
        "event_date": "2026-07-02",
        "details": {"fund": fund, "change": change, "period": "2026-06-30",
                    "filed_at": "2026-07-02"},
    }


def _insider(ticker: str, insider: str, filing_date: str = "2026-07-01") -> dict:
    return {
        "source": SOURCE_INSIDER,
        "ticker": ticker,
        "event_key": f"{insider}-{filing_date}",
        "event_date": filing_date,
        "details": {"insider": insider, "role": "officer (CEO)", "filing_date": filing_date,
                     "transaction_date": "2026-06-30", "shares": 1000.0, "price": 10.0,
                     "value": 10000.0},
    }


def _theme(ticker: str, theme: str) -> dict:
    return {
        "source": SOURCE_NEWS_THEME,
        "ticker": ticker,
        "event_key": f"{theme}-2026-07-03",
        "event_date": "2026-07-03",
        "details": {"theme": theme, "hits": 5, "sources": ["a", "b"]},
    }


def _eightk(ticker: str, accession: str, items: list[str], filing_date: str = "2026-07-05") -> dict:
    return {
        "source": SOURCE_8K,
        "ticker": ticker,
        "event_key": accession,
        "event_date": filing_date,
        "details": {"items": items, "filing_date": filing_date, "published_at": f"{filing_date}T20:30:00.000Z"},
    }


def test_evidence_block_renders_8k_filing():
    block = evidence_block([_eightk("EXE", "0000320193-26-000011", ["2.02"])])
    assert block is not None
    assert "8-K eingereicht, Item 2.02 (gemeldet 2026-07-05)" in block
    assert DELAY_NOTE in block


def test_evidence_block_deduplicates_repeated_8k_filings():
    block = evidence_block(
        [
            _eightk("EXE", "0000320193-26-000011", ["2.02"]),
            _eightk("EXE", "0000320193-26-000011", ["2.02"]),
        ]
    )
    assert block is not None
    assert block.count("8-K eingereicht") == 1


def test_8k_alone_never_triggers_an_alert():
    clusters = {"EXE": [_eightk("EXE", "0000320193-26-000011", ["2.02", "9.01"])]}
    assert select_evidence_alerts(clusters) == []


def test_evidence_block_renders_all_three_sources_with_delay_note():
    block = evidence_block(
        [
            _congress("EXE", "Jane Doe"),
            _congress("EXE", "John Roe", filing_date="2026-07-03"),
            _fund("EXE", "Scion Asset Management"),
            _theme("EXE", "ai chips"),
        ]
    )
    assert block is not None
    assert block.startswith("Externe Signale:")
    # Two distinct buyers collapse into one line naming the first + a count.
    assert "2 Kongress-Kauf/Käufe gemeldet (Jane Doe +1 weitere, zuletzt 2026-07-03)" in block
    assert "Scion Asset Management: neue Position (Q-Ende 2026-06-30, gemeldet 2026-07-02)" in block
    assert "News-Thema »ai chips« (5 Schlagzeilen, 2 Quellen)" in block
    assert DELAY_NOTE in block


def test_evidence_block_returns_none_when_empty():
    assert evidence_block([]) is None


def test_evidence_block_deduplicates_repeated_themes():
    block = evidence_block([_theme("EXE", "ai chips"), _theme("EXE", "ai chips")])
    assert block is not None
    assert block.count("ai chips") == 1


def test_evidence_block_renders_insider_purchases():
    block = evidence_block(
        [
            _insider("EXE", "Cook Timothy D"),
            _insider("EXE", "Jane Insider", filing_date="2026-07-04"),
        ]
    )
    assert block is not None
    assert "2 Insider-Kauf/Käufe gemeldet (Cook Timothy D +1 weitere, zuletzt 2026-07-04)" in block
    assert DELAY_NOTE in block


def test_select_evidence_alerts_requires_a_genuine_cluster():
    clusters = {
        "ONE": [_congress("ONE", "Jane Doe")],  # single buyer -> noise
        "TWO": [_congress("TWO", "Jane Doe"), _congress("TWO", "John Roe")],
        "FUND": [_fund("FUND", "Scion Asset Management"), _fund("FUND", "Baupost Group")],
        "MIX": [_congress("MIX", "Jane Doe"), _fund("MIX", "Scion Asset Management")],
        "NEWS": [_theme("NEWS", "ai chips"), _theme("NEWS", "rate cuts")],  # themes never alert
    }
    alerts = select_evidence_alerts(clusters)
    assert [a["ticker"] for a in alerts] == ["FUND", "TWO"]
    assert alerts[1]["reasons"] == ["2 Kongress-Mitglieder haben gekauft"]
    assert alerts[0]["reasons"] == ["2 beobachtete Fonds neu/aufgestockt"]


def test_select_evidence_alerts_requires_min_insiders_cluster():
    clusters = {
        "TWO": [_insider("TWO", "A"), _insider("TWO", "B")],  # below MIN_INSIDERS=3 -> noise
        "THREE": [_insider("THREE", "A"), _insider("THREE", "B"), _insider("THREE", "C")],
    }
    alerts = select_evidence_alerts(clusters)
    assert [a["ticker"] for a in alerts] == ["THREE"]
    assert alerts[0]["reasons"] == ["3 Insider haben unabhängig gekauft"]


def test_distinct_buyer_count_counts_unique_names_across_sources():
    events = [
        _congress("MIX", "Jane Doe"),
        _fund("MIX", "Scion Asset Management"),
        _insider("MIX", "Cook Timothy D"),
        _insider("MIX", "Cook Timothy D", filing_date="2026-07-05"),  # same person, not double
    ]
    assert distinct_buyer_count(events) == 3


def test_build_alert_text_marks_escalation():
    alerts = select_evidence_alerts(
        {"EXE": [_congress("EXE", "Jane Doe"), _congress("EXE", "John Roe")]}
    )
    text = build_alert_text(alerts[0], escalated=True)
    assert "Eskalation: mehr Käufer als beim letzten Alarm" in text
    plain = build_alert_text(alerts[0])
    assert "Eskalation" not in plain


def test_build_alert_text_is_labelled_as_not_a_screener_pick():
    alerts = select_evidence_alerts(
        {"EXE": [_congress("EXE", "Jane Doe"), _congress("EXE", "John Roe")]}
    )
    text = build_alert_text(alerts[0])
    assert text.startswith("🔎 Evidenz-Alarm: EXE — kein Screener-Pick")
    assert "• 2 Kongress-Mitglieder haben gekauft" in text
    assert DELAY_NOTE in text
    assert "dieser Hinweis kommt NICHT aus dem Faktor-Screener" in text
    assert "Keine Anlageberatung." in text


def _score_index(person: str = "Jane Doe", weighted: float = 0.05) -> dict:
    return {
        (person, SOURCE_CONGRESS): {
            "person": person, "source": SOURCE_CONGRESS, "n_calls": 12,
            "n_unresolvable": 1, "hit_rate_short": 0.5, "hit_rate_long": 0.58,
            "mean_abnormal_short": 0.01, "mean_abnormal_long": 0.03,
            "weighted_score": weighted, "scoreable": True,
        }
    }


def test_attach_track_records_annotates_only_gated_persons():
    from equity_scout.evidence.aggregate import attach_track_records

    index = _score_index()
    index[("Thin Sample", SOURCE_CONGRESS)] = {
        **index[("Jane Doe", SOURCE_CONGRESS)], "person": "Thin Sample",
        "scoreable": False, "weighted_score": None,
    }
    clusters = {
        "EXE": [_congress("EXE", "Jane Doe"), _congress("EXE", "Thin Sample")]
    }
    attach_track_records(clusters, index)
    jane, thin = clusters["EXE"]
    assert "Track-Record: 12 Käufe, 58 % Treffer 3M" in jane["details"]["track_record"]["note"]
    assert "track_record" not in thin["details"]  # "zu wenig Daten" stays a non-statement


def test_evidence_block_carries_track_record_lines():
    from equity_scout.evidence.aggregate import attach_track_records

    clusters = attach_track_records(
        {"EXE": [_congress("EXE", "Jane Doe"), _congress("EXE", "John Roe")]},
        _score_index(),
    )
    block = evidence_block(clusters["EXE"])
    assert "• Jane Doe — Track-Record: 12 Käufe" in block
    assert "Historie, keine Prognose" in block


def test_single_buyer_with_strong_track_record_alerts_alone():
    from equity_scout.evidence.aggregate import attach_track_records

    clusters = attach_track_records(
        {"SOLO": [_congress("SOLO", "Jane Doe")]}, _score_index(weighted=0.05)
    )
    alerts = select_evidence_alerts(clusters)
    assert len(alerts) == 1
    assert "starker gemessener Track-Record (12 Käufe, Ø +5.0 % vs SPY 3M" in (
        alerts[0]["reasons"][0]
    )
    assert "Historie, keine Prognose" in alerts[0]["reasons"][0]


def test_single_buyer_below_score_bar_stays_noise():
    from equity_scout.evidence.aggregate import attach_track_records

    clusters = attach_track_records(
        {"SOLO": [_congress("SOLO", "Jane Doe")]}, _score_index(weighted=0.01)
    )
    assert select_evidence_alerts(clusters) == []


def test_attach_track_records_skips_rows_with_unmeasured_long_horizon():
    """A stale person_scores row may carry scoreable=True with None long-horizon
    fields (older gate definition): it must not annotate — a coalesced 0 % would
    be a fabricated number (review finding 2026-07-11)."""
    from equity_scout.evidence.aggregate import attach_track_records

    index = _score_index()
    index[("Jane Doe", SOURCE_CONGRESS)] = {
        **index[("Jane Doe", SOURCE_CONGRESS)],
        "hit_rate_long": None, "mean_abnormal_long": None, "weighted_score": None,
    }
    clusters = attach_track_records({"EXE": [_congress("EXE", "Jane Doe")]}, index)
    assert "track_record" not in clusters["EXE"][0]["details"]
    assert select_evidence_alerts(clusters) == []


def _voice(ticker: str, kind: str, direction: str | None = None) -> dict:
    details = {
        "speaker": "Michael Burry",
        "kind": kind,
        "headline": "Michael Burry buys Apple shares",
        "feed": "google-news",
        "published": "2026-07-12",
    }
    if direction:
        details["direction"] = direction
    return {
        "source": "voice",
        "ticker": ticker,
        "event_key": "michael-burry-bullish-2026w29",
        "event_date": "2026-07-12",
        "details": details,
    }


def test_evidence_block_renders_voice_call_and_context_lines():
    block = evidence_block(
        [_voice("AAPL", "call", "bullish"), _voice("AAPL", "context")]
    )
    assert block is not None
    assert "Stimme: Michael Burry äußert sich positiv" in block
    # context uses a different headline to dodge the (speaker, headline) dedupe
    context = _voice("AAPL", "context")
    context["details"]["headline"] = "What Michael Burry thinks about Apple"
    block = evidence_block([_voice("AAPL", "call", "bullish"), context])
    assert block is not None
    assert "Stimme: Michael Burry erwähnt" in block
    assert DELAY_NOTE in block


def test_voice_call_alerts_alone_but_context_never_does():
    call_alerts = select_evidence_alerts({"AAPL": [_voice("AAPL", "call", "bullish")]})
    assert len(call_alerts) == 1
    assert any("Stimme: Michael Burry" in r for r in call_alerts[0]["reasons"])
    assert any("kein Filing" in r for r in call_alerts[0]["reasons"])

    bearish = select_evidence_alerts(
        {"TSLA": [_voice("TSLA", "call_bearish", "bearish")]}
    )
    assert len(bearish) == 1
    assert any("äußert sich negativ" in r for r in bearish[0]["reasons"])

    assert select_evidence_alerts({"AAPL": [_voice("AAPL", "context")]}) == []


def test_voice_events_never_trigger_the_bought_worded_strong_buyer_path():
    from equity_scout.evidence.aggregate import attach_track_records

    index = {
        ("Michael Burry", "voice"): {
            "scoreable": True, "n_calls": 9, "hit_rate_long": 0.8,
            "weighted_score": 0.05,
        }
    }
    clusters = attach_track_records({"AAPL": [_voice("AAPL", "context")]}, index)
    alerts = select_evidence_alerts(clusters)
    assert alerts == []  # a mention with a strong record is still not a purchase
