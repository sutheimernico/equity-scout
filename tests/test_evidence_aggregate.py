"""German evidence surfaces: pitch block, alert selection, alert text.

Every surface must carry the structural-delay honesty note; alerts must be
unmistakably labelled as NOT coming from the screener (no score, no buttons).
"""
from __future__ import annotations

from equity_scout.evidence.aggregate import (
    DELAY_NOTE,
    build_alert_text,
    evidence_block,
    select_evidence_alerts,
)
from equity_scout.evidence.base import SOURCE_13F, SOURCE_CONGRESS, SOURCE_NEWS_THEME


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


def _theme(ticker: str, theme: str) -> dict:
    return {
        "source": SOURCE_NEWS_THEME,
        "ticker": ticker,
        "event_key": f"{theme}-2026-07-03",
        "event_date": "2026-07-03",
        "details": {"theme": theme, "hits": 5, "sources": ["a", "b"]},
    }


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
