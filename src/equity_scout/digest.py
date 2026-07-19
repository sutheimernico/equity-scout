"""Daily e-mail digest of the decision inbox.

Rendering is pure; sending goes through an injectable smtp_factory (defaults to
smtplib.SMTP_SSL) so tests never open sockets. Config is fail-safe like the
telegram client: missing/malformed env -> None + stderr hint, never a crash.
"""
from __future__ import annotations

import smtplib
import sys
from email.message import EmailMessage

from equity_scout.constants import SHORT_DISCLAIMER
from equity_scout.pitch import VERDICT_EMOJI, compute_verdict
from equity_scout.telegram_client import escape_html

# Past-tense digest wording deliberately differs from telegram_client.DECISION_LABELS'
# imperative button labels (a report reads differently from a button) — not drift.
_STATUS_ICON = {"open": "📬 offen", "buy": "✅ Kaufentscheidung",
                "pass": "❌ abgelehnt", "later": "⏸ später"}
# Human labels for evidence.base SOURCE_* keys; unknown keys fall back to themselves.
_SOURCE_LABEL = {"congress": "Kongress-Käufe", "thirteen_f": "13F-Fonds",
                 "news_theme": "News-Themen", "insider": "Insider-Käufe (Form 4)"}

# v9: the real inbox accumulates cooldown re-pitches (same ticker up to 3x) and grows
# past what the beginner persona can scan in one sitting — cap the rendered lines and
# dedupe per ticker so the section stays a skimmable top-of-list, not a lifetime log.
OPEN_PITCH_CAP = 6
_VERDICT_ORDER = {"green": 0, "yellow": 1, "red": 2}


def _dedupe_open(open_pitches: list[dict]) -> list[dict]:
    """Newest row per ticker (cooldown re-pitches accumulate otherwise), green
    verdicts first, newest first within a band; verdict-less legacy rows sort with
    yellow. Pure list math — rendering stays a straight loop."""
    newest: dict[str, dict] = {}
    for p in sorted(open_pitches, key=lambda p: p["created_at"], reverse=True):
        newest.setdefault(p["ticker"], p)
    rows = sorted(newest.values(), key=lambda p: p["created_at"], reverse=True)
    rows.sort(key=lambda p: _VERDICT_ORDER.get(p.get("verdict"), 1))
    return rows


def load_smtp_config(env: dict) -> dict | None:
    required = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO")
    if any(not env.get(key) for key in required):
        return None
    try:
        port = int(env["SMTP_PORT"])
    except ValueError:
        print("SMTP_PORT is not an integer — digest disabled.", file=sys.stderr)
        return None
    return {
        "host": env["SMTP_HOST"], "port": port, "user": env["SMTP_USER"],
        "password": env["SMTP_PASSWORD"], "to": env["DIGEST_TO"],
    }


def build_digest(
    pitches: list[dict],
    *,
    date_label: str,
    decided_since: str | None = None,
    evidence_stats: dict[str, dict] | None = None,
    alerts_today: list[dict] | None = None,
    opportunities: list[dict] | None = None,
    earnings_this_week: list[dict] | None = None,
    regime: dict | None = None,
    sector_line: str | None = None,
    below_threshold: int | None = None,
    html: bool = False,
) -> str:
    """German digest: market head first, all open pitches, then recent decisions.

    decided_since (UTC ISO string) scopes the decided section to a window — without it
    every decision ever made would reappear daily. Lexicographic >= is chronologically
    correct because all writers produce UTC "+00:00" ISO strings (see inbox_storage).
    evidence_stats (evidence.ledger.stats_by_source shape) appends the measured
    per-source hit-rates — queries, not promises; omitted entirely when None/empty.
    alerts_today (evidence.storage.load_alerts rows), opportunities (radar watchlist
    entries) and earnings_this_week (earnings_storage.earnings_within rows: ticker +
    earnings_date) render the day-summary sections for the Telegram daily chat; all
    three are omitted entirely when None/empty.

    v8: `regime` (regime.build_regime shape) and `sector_line` (sectors.top_sector_line)
    render the at-a-glance market head — both omitted when None, an honest absence.
    `below_threshold` reports how many watchlist names sat under the quality gate today
    (A4 transparency). `html=True` renders Telegram HTML: bold section heads, escaped
    dynamic content, one <b> pair per line so line-based splitting can never sever a tag;
    the SMTP/stdout path stays plain.

    v9: open-pitch lines carry their persisted pitches.verdict traffic light (that
    stored value never contradicts the pitch it summarizes — the whole point of
    storing it in v8) and are deduped/sorted/capped (see `_dedupe_open`); opportunity
    lines compute one live verdict instead, since watchlist entries never had one
    persisted."""

    def _head(text: str) -> str:
        return f"<b>{escape_html(text)}</b>" if html else text

    def _line(text: str) -> str:
        return escape_html(text) if html else text

    lines = [_head(f"Copilot-Digest {date_label}")]
    if regime is not None:
        lines.append(_line(
            f"{regime['emoji']} Marktlage: {regime['label']}"
            f" ({regime['green_count']}/{regime['available']} Signale grün)"
        ))
    if sector_line is not None:
        lines.append(_line(f"📊 {sector_line}"))
    lines.append("")
    if alerts_today:
        lines.append(_head("📌 Heute aufgefallen:"))
        for alert in alerts_today:
            # Voice reasons carry whole press headlines — cap them so the digest scans
            # as a list (Nico 2026-07-15: kurz und übersichtlich).
            reasons = ", ".join(
                (r if len(r) <= 90 else r[:89] + "…")
                for r in (_SOURCE_LABEL.get(r, r) for r in alert["reasons"])
            )
            buyers = alert.get("buyer_count") or 0
            suffix = f" ({buyers} Käufer)" if buyers > 1 else ""
            lines.append(_line(f"  {alert['ticker']}: {reasons}{suffix}"))
        lines.append("")
    if opportunities:
        lines.append(_head("🎯 Chancen im Blick:"))
        for entry in opportunities:
            marks = ""
            if entry.get("in_zone"):
                marks += " · in Zone"
            if (entry.get("value_gap") or 0) > 0:
                marks += " · unterbewertet"
            base = f"{entry['ticker']} · Score {round(entry['composite'] * 100)}/100{marks}"
            try:
                verdict = compute_verdict(entry)
            except KeyError:
                # Minimal/pre-v8 watchlist entries can lack "breakdown" — degrade to the
                # plain line instead of crashing the whole digest over one missing field.
                lines.append(_line(f"  {base}"))
                continue
            lines.append(_line(f"  {verdict['emoji']} {base} — {verdict['label']}"))
        lines.append("")
    if earnings_this_week:
        lines.append(_head("📅 Earnings diese Woche:"))
        for e in earnings_this_week:
            lines.append(_line(f"  {e['ticker']}: {e['earnings_date']}"))
        lines.append("")
    open_pitches = _dedupe_open([p for p in pitches if p["status"] == "open"])
    decided = [
        p for p in pitches
        if p["status"] != "open"
        and (decided_since is None or (p["decided_at"] or "") >= decided_since)
    ]
    if not open_pitches:
        lines.append(_line("Aktuell keine offenen Pitches."))
    else:
        # count style ("Offene Pitches: 1") dodges singular/plural agreement; the count
        # is per TICKER (post-dedupe), matching what's actually rendered below.
        lines.append(_head(f"Offene Pitches: {len(open_pitches)}"))
        for p in open_pitches[:OPEN_PITCH_CAP]:
            # v9: the same verdict already persisted on the pitch at notify time
            # (pitch.compute_verdict, see inbox_storage) — "📬" is only the honest
            # fallback for pre-v8 rows that never had a verdict computed/stored.
            icon = VERDICT_EMOJI.get(p.get("verdict"), "📬")
            why = f" — {p['verdict_why']}" if p.get("verdict_why") else ""
            lines.append(_line(
                f"  {icon} {p['ticker']} · Score {round(p['composite'] * 100)}/100"
                f" · Kurs {p['price']:.2f} · seit {p['created_at'][:10]}{why}"
            ))
        rest = len(open_pitches) - OPEN_PITCH_CAP
        if rest > 0:
            # No inflection ("weitere" stays invariant for 1 and n) so this doesn't need
            # a singular/plural branch — same dodge as the "Offene Pitches: N" header.
            lines.append(_line(f"  … {rest} weitere im Dashboard."))
    if below_threshold:
        lines.append(_line(
            f"  ({below_threshold} Watchlist-Titel unter der Qualitätsschwelle —"
            " bewusst nicht gepitcht)"
        ))
    if decided:
        lines.append("")
        lines.append(_head("Entschieden:"))
        for p in decided:
            icon = _STATUS_ICON.get(p["status"], p["status"])
            lines.append(_line(f"  {icon} — {p['ticker']} · am {(p['decided_at'] or '')[:10]}"))
    if evidence_stats:
        lines.append("")
        lines.append(_head("Evidenz-Quellen — gemessene Trefferquote vs SPY (60-Tage-Horizont):"))
        for source in sorted(evidence_stats):
            entry = evidence_stats[source]
            if entry["n_resolved"] == 0:
                measured = "noch nichts aufgelöst"
            else:
                measured = (
                    f"{entry['n_resolved']} aufgelöst,"
                    f" Trefferquote {round(entry['hit_rate'] * 100)} %,"
                    f" Ø relative Rendite {entry['mean_relative_return'] * 100:+.1f} %"
                )
            lines.append(_line(f"  {_SOURCE_LABEL.get(source, source)}: {measured}"
                               f" · offen: {entry['n_open']}"))
    lines += ["", SHORT_DISCLAIMER]
    return "\n".join(lines)


def send_digest(config: dict, subject: str, body: str, smtp_factory=smtplib.SMTP_SSL) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config["user"]
    msg["To"] = config["to"]
    msg.set_content(body)
    with smtp_factory(config["host"], config["port"]) as smtp:
        smtp.login(config["user"], config["password"])
        smtp.send_message(msg)
