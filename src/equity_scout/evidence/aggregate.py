"""German text surfaces for evidence: the pitch block and off-watchlist alerts.

Both surfaces carry the structural-delay note — congress filings lag up to 45 days,
13F filings up to 135 days after the quarter's trades — because the single most
dangerous misreading of this data is "früh dabei sein". Evidence NEVER changes the
entry composite or selection rules; alerts are explicitly labelled as NOT coming
from the screener (no valuation, no entry score, no decision buttons).
"""
from __future__ import annotations

from equity_scout.constants import SHORT_DISCLAIMER
from equity_scout.evidence.base import SOURCE_13F, SOURCE_CONGRESS, SOURCE_NEWS_THEME

DELAY_NOTE = (
    "Externe Signale sind Kontext, kein Frühsignal: Kongress-Meldungen kommen bis zu "
    "45 Tage, 13F-Meldungen bis zu 135 Tage nach dem Kauf."
)

_CHANGE_LABEL = {"new": "neue Position", "increased": "Position aufgestockt"}


def _congress_line(events: list[dict]) -> str | None:
    buys = [e for e in events if e["source"] == SOURCE_CONGRESS]
    if not buys:
        return None
    politicians = []
    for event in buys:
        name = event["details"].get("politician") or "unbekannt"
        if name not in politicians:
            politicians.append(name)
    latest = max(e["details"].get("filing_date") or e["event_date"] for e in buys)
    who = politicians[0] if len(politicians) == 1 else (
        f"{politicians[0]} +{len(politicians) - 1} weitere"
    )
    return (
        f"• {len(buys)} Kongress-Kauf/Käufe gemeldet ({who}, zuletzt {latest})"
    )


def _fund_lines(events: list[dict]) -> list[str]:
    return [
        f"• {e['details'].get('fund', 'Fonds')}: {_CHANGE_LABEL.get(e['details'].get('change'), e['details'].get('change', '?'))} "
        f"(Q-Ende {e['details'].get('period', '?')}, gemeldet {e['details'].get('filed_at', '?')})"
        for e in events
        if e["source"] == SOURCE_13F
    ]


def _theme_lines(events: list[dict]) -> list[str]:
    lines = []
    seen: set[str] = set()
    for event in events:
        if event["source"] != SOURCE_NEWS_THEME:
            continue
        theme = event["details"].get("theme", "?")
        if theme in seen:
            continue
        seen.add(theme)
        lines.append(
            f"• News-Thema »{theme}« ({event['details'].get('hits', '?')} Schlagzeilen, "
            f"{len(event['details'].get('sources', []))} Quellen)"
        )
    return lines


def evidence_block(events: list[dict]) -> str | None:
    """The pitch's "Externe Signale" section, or None when there is nothing to say."""
    lines = []
    congress = _congress_line(events)
    if congress:
        lines.append(congress)
    lines += _fund_lines(events)
    lines += _theme_lines(events)
    if not lines:
        return None
    return "\n".join(["Externe Signale:", *lines, DELAY_NOTE])


def select_evidence_alerts(
    clusters: dict[str, list[dict]],
    *,
    min_congress_buyers: int = 2,
    min_funds: int = 2,
) -> list[dict]:
    """Off-watchlist tickers with a genuine evidence CLUSTER — one politician's buy is
    noise, several distinct buyers (or several tracked funds moving in) is worth a look.
    Themes alone never alert: they are the weakest, most-priced-in source."""
    alerts: list[dict] = []
    for ticker, events in sorted(clusters.items()):
        politicians = {
            e["details"].get("politician")
            for e in events
            if e["source"] == SOURCE_CONGRESS
        } - {None}
        funds = {
            e["details"].get("fund") for e in events if e["source"] == SOURCE_13F
        } - {None}
        reasons = []
        if len(politicians) >= min_congress_buyers:
            reasons.append(f"{len(politicians)} Kongress-Mitglieder haben gekauft")
        if len(funds) >= min_funds:
            reasons.append(f"{len(funds)} beobachtete Fonds neu/aufgestockt")
        if reasons:
            alerts.append({"ticker": ticker, "reasons": reasons, "events": events})
    return alerts


def build_alert_text(alert: dict) -> str:
    """Plain notification without decision buttons: an alert asks for a LOOK, it is
    not a screener pitch and must not feed the arena's decision lanes."""
    header = f"🔎 Evidenz-Alarm: {alert['ticker']} — kein Screener-Pick"
    reason_lines = [f"• {reason}" for reason in alert["reasons"]]
    block = evidence_block(alert["events"]) or ""
    footer = (
        "Kein Entry-Score, keine Bewertung — dieser Hinweis kommt NICHT aus dem "
        f"Faktor-Screener. {SHORT_DISCLAIMER}"
    )
    parts = [header, "\n".join(reason_lines), block, footer]
    return "\n\n".join(part for part in parts if part)
