"""German text surfaces for evidence: the pitch block and off-watchlist alerts.

Every surface carries the structural-delay note — congress filings lag up to 45 days,
13F filings up to 135 days, Form 4 insider filings up to 2 business days after the
trade — because the single most dangerous misreading of this data is "früh dabei
sein" (even the fastest source is still a lag, not an early signal). Evidence NEVER
changes the entry composite or selection rules; alerts are explicitly labelled as NOT
coming from the screener (no valuation, no entry score, no decision buttons).
"""
from __future__ import annotations

from equity_scout.constants import SHORT_DISCLAIMER
from equity_scout.evidence.base import (
    SOURCE_13F,
    SOURCE_CONGRESS,
    SOURCE_INSIDER,
    SOURCE_NEWS_THEME,
    SOURCE_VOICE,
)

DELAY_NOTE = (
    "Externe Signale sind Kontext, kein Frühsignal: Kongress-Meldungen kommen bis zu "
    "45 Tage, 13F-Meldungen bis zu 135 Tage, Insider-Meldungen (Form 4) bis zu 2 "
    "Werktage nach dem Kauf. Presse-Stimmen sind bereits öffentlich, wenn sie hier "
    "auftauchen."
)

_CHANGE_LABEL = {"new": "neue Position", "increased": "Position aufgestockt"}

# A single buyer may alert alone only above this recency-weighted mean abnormal
# return @3M vs SPY — and only with a gated sample (scoreable). History, no forecast.
MIN_SINGLE_BUYER_SCORE = 0.02

# >=3 distinct insiders on the same ticker inside the alert window. Cohen/Malloy/
# Pomorski (2012, "Decoding Inside Information") find that CLUSTERED insider buying
# (several insiders independently buying) predicts returns far better than any single
# insider's routine purchase — one buy is noise, a cluster is the robust signal, same
# reasoning as min_congress_buyers/min_funds below.
MIN_INSIDERS = 3


def _person_of(event: dict) -> str | None:
    details = event.get("details") or {}
    return (
        details.get("politician")
        or details.get("fund")
        or details.get("insider")
        or details.get("speaker")
    )


def distinct_buyer_count(events: list[dict]) -> int:
    """Unique named buyers across ALL sources in one cluster's events — F4's basis for
    breaking a cooldown when a cluster has genuinely grown (notify.send_evidence_alerts)."""
    return len({_person_of(e) for e in events} - {None})


def track_record_note(score_row: dict) -> str:
    """One honest German line for a measured person score (always carries n + caveat).

    Callers must pass a row whose long-horizon fields are measured (attach_track_records
    gates on that) — no `or 0` coalescing here: an unmeasured horizon must never render
    as a fabricated 0 %."""
    return (
        f"Track-Record: {score_row['n_calls']} Käufe,"
        f" {round(score_row['hit_rate_long'] * 100)} % Treffer 3M,"
        f" Ø {score_row['weighted_score'] * 100:+.1f} % vs SPY"
        " — Historie, keine Prognose"
    )


def attach_track_records(
    clusters: dict[str, list[dict]], score_index: dict[tuple[str, str], dict]
) -> dict[str, list[dict]]:
    """Annotate events whose person has a MEASURED, gated score (person_storage index).

    Ungated persons stay unannotated on purpose: "zu wenig Daten" is a non-statement,
    not a bad score. Returns the same dict for chaining; events are annotated in place.
    """
    for events in clusters.values():
        for event in events:
            person = _person_of(event)
            if not person:
                continue
            row = score_index.get((person, event["source"]))
            # Belt and braces beside `scoreable`: rows persisted under an older gate
            # definition may combine scoreable=True with unmeasured long-horizon fields —
            # those must never render (a coalesced 0 % would be a fabricated number).
            if row and row["scoreable"] and row["weighted_score"] is not None:
                event["details"]["track_record"] = {
                    "note": track_record_note(row),
                    "weighted_score": row["weighted_score"],
                    "n_calls": row["n_calls"],
                }
    return clusters


def _track_record_lines(events: list[dict]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for event in events:
        person = _person_of(event)
        record = (event.get("details") or {}).get("track_record")
        if not person or person in seen or not record:
            continue
        seen.add(person)
        lines.append(f"• {person} — {record['note']}")
    return lines


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


def _insider_line(events: list[dict]) -> str | None:
    buys = [e for e in events if e["source"] == SOURCE_INSIDER]
    if not buys:
        return None
    insiders = []
    for event in buys:
        name = event["details"].get("insider") or "unbekannt"
        if name not in insiders:
            insiders.append(name)
    latest = max(e["details"].get("filing_date") or e["event_date"] for e in buys)
    who = insiders[0] if len(insiders) == 1 else (
        f"{insiders[0]} +{len(insiders) - 1} weitere"
    )
    return f"• {len(buys)} Insider-Kauf/Käufe gemeldet ({who}, zuletzt {latest})"


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


_DIRECTION_LABEL = {"bullish": "äußert sich positiv", "bearish": "äußert sich negativ"}


def _voice_lines(events: list[dict]) -> list[str]:
    """Measured calls first (they carry a direction), context mentions after; one line
    per (speaker, headline) — the same syndicated story must not repeat."""
    calls: list[str] = []
    mentions: list[str] = []
    seen: set[tuple[str, str]] = set()
    for event in events:
        if event["source"] != SOURCE_VOICE:
            continue
        details = event.get("details") or {}
        speaker = details.get("speaker", "unbekannt")
        headline = details.get("headline", "?")
        if (speaker, headline) in seen:
            continue
        seen.add((speaker, headline))
        if details.get("kind") == "context":
            mentions.append(f"• Stimme: {speaker} erwähnt — »{headline}«")
        else:
            verb = _DIRECTION_LABEL.get(details.get("direction", ""), "äußert sich")
            calls.append(f"• Stimme: {speaker} {verb} — »{headline}«")
    return calls + mentions


def evidence_block(events: list[dict]) -> str | None:
    """The pitch's "Externe Signale" section, or None when there is nothing to say."""
    lines = []
    congress = _congress_line(events)
    if congress:
        lines.append(congress)
    insider = _insider_line(events)
    if insider:
        lines.append(insider)
    lines += _fund_lines(events)
    lines += _voice_lines(events)
    lines += _theme_lines(events)
    if not lines:
        return None
    lines += _track_record_lines(events)
    return "\n".join(["Externe Signale:", *lines, DELAY_NOTE])


def evidence_summary_lines(events: list[dict], limit: int = 2, width: int = 90) -> list[str]:
    """The evidence block's strongest lines, caption-compact: chart-photo captions cap at
    1024 chars, so 'wer kauft/redet' must fit in one or two short lines."""
    lines: list[str] = []
    for candidate in (_congress_line(events), _insider_line(events)):
        if candidate:
            lines.append(candidate)
    lines += _fund_lines(events)
    lines += _voice_lines(events)
    return [ln if len(ln) <= width else ln[: width - 1] + "…" for ln in lines[:limit]]


def select_evidence_alerts(
    clusters: dict[str, list[dict]],
    *,
    min_congress_buyers: int = 2,
    min_funds: int = 2,
    min_insiders: int = MIN_INSIDERS,
    min_single_buyer_score: float = MIN_SINGLE_BUYER_SCORE,
) -> list[dict]:
    """Off-watchlist tickers with a genuine evidence CLUSTER — one politician's buy is
    noise, several distinct buyers (or several tracked funds moving in, or several
    insiders independently buying) is worth a look. Exception: a SINGLE buyer whose
    MEASURED track record (attach_track_records; gated sample, recency-weighted
    abnormal return @3M vs SPY) clears the bar alerts alone — history, never a
    forecast. Themes alone never alert: they are the weakest, most-priced-in source."""
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
        insiders = {
            e["details"].get("insider") for e in events if e["source"] == SOURCE_INSIDER
        } - {None}
        reasons = []
        if len(politicians) >= min_congress_buyers:
            reasons.append(f"{len(politicians)} Kongress-Mitglieder haben gekauft")
        if len(funds) >= min_funds:
            reasons.append(f"{len(funds)} beobachtete Fonds neu/aufgestockt")
        if len(insiders) >= min_insiders:
            reasons.append(f"{len(insiders)} Insider haben unabhängig gekauft")
        # A tracked person's MEASURABLE public call (voices.py's deterministic
        # name-before-verb + unambiguous-ticker rule) alerts alone: the persons list is
        # curated, such calls are rare, and the cooldown caps repeats. Context mentions
        # never alert — a mention is not a statement.
        voice_seen: set[str] = set()
        for event in events:
            details = event.get("details") or {}
            if event["source"] != SOURCE_VOICE or details.get("kind") == "context":
                continue
            speaker = details.get("speaker")
            if not speaker or speaker in voice_seen:
                continue
            voice_seen.add(speaker)
            verb = _DIRECTION_LABEL.get(details.get("direction", ""), "äußert sich")
            reasons.append(
                f"Stimme: {speaker} {verb} — »{details.get('headline', '?')}«"
                " (Presse-Schlagzeile, kein Filing)"
            )
        strong_seen: set[str] = set()
        for event in events:
            # Voice events never enter the "hat gekauft"-worded strong-buyer path: a
            # public statement is not a purchase, and measurable voice calls already
            # alert via their own reason line above.
            if event["source"] == SOURCE_VOICE:
                continue
            person = _person_of(event)
            record = (event.get("details") or {}).get("track_record")
            if not person or person in strong_seen or not record:
                continue
            # attach_track_records only annotates measured records — no None here.
            if record["weighted_score"] >= min_single_buyer_score:
                strong_seen.add(person)
                reasons.append(
                    f"{person} hat gekauft — starker gemessener Track-Record"
                    f" ({record['n_calls']} Käufe,"
                    f" Ø {record['weighted_score'] * 100:+.1f} % vs SPY 3M;"
                    " Historie, keine Prognose)"
                )
        if reasons:
            alerts.append({"ticker": ticker, "reasons": reasons, "events": events})
    return alerts


def build_alert_text(alert: dict, *, escalated: bool = False) -> str:
    """Plain notification without decision buttons: an alert asks for a LOOK, it is
    not a screener pitch and must not feed the arena's decision lanes.

    `escalated` (F4, notify.send_evidence_alerts): the cluster's distinct-buyer count
    grew past the ticker's last SENT alert, breaking through the cooldown — the header
    marks this so the escalation reads differently from a routine repeat alert.
    """
    header = f"🔎 Evidenz-Alarm: {alert['ticker']} — kein Screener-Pick"
    if escalated:
        header += " — Eskalation: mehr Käufer als beim letzten Alarm"
    reason_lines = [f"• {reason}" for reason in alert["reasons"]]
    block = evidence_block(alert["events"]) or ""
    footer = (
        "Kein Entry-Score, keine Bewertung — dieser Hinweis kommt NICHT aus dem "
        f"Faktor-Screener. {SHORT_DISCLAIMER}"
    )
    parts = [header, "\n".join(reason_lines), block, footer]
    return "\n\n".join(part for part in parts if part)
