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

# A rebalance that moves less than 1 % of the book is bookkeeping, not news: the nightly
# advance routinely produces a dozen of them (12 trades, largest ~60 USD, on 2026-08-03).
# Name the material ones, count the rest — the full list lives in the cockpit.
MATERIAL_DELTA_WEIGHT = 0.01
TRADE_NAME_CAP = 3


# German number rendering: thousands dot, decimal comma, U+2212 minus for negatives.
# Telegram shows these lines next to German prose, so English 1,234.5 reads as a typo.
# PUBLIC (no underscore) because scripts/run_autotrader.py formats the same figures for
# the nightly push — one formatter, so the two Telegram surfaces cannot drift.
def format_de(value: float, digits: int = 0) -> str:
    formatted = f"{abs(value):,.{digits}f}".replace(",", " ").replace(".", ",")
    formatted = formatted.replace(" ", ".")
    return f"−{formatted}" if value < 0 else formatted


def format_de_pct(value: float, digits: int = 1) -> str:
    """Signed percent from a RATIO (0.012 -> '+1,2 %')."""
    sign = "+" if value >= 0 else "−"
    return f"{sign}{format_de(abs(value) * 100, digits)} %"


def _trade_summary(trades: list[dict]) -> str:
    """'Trades: ↓MU 4,1 % · +2 kleine' — or an honest 'Keine Trades'."""
    if not trades:
        return "Keine Trades an diesem Stand."
    material = sorted(
        (t for t in trades if abs(t["delta_weight"]) >= MATERIAL_DELTA_WEIGHT),
        key=lambda t: abs(t["delta_weight"]), reverse=True,
    )
    named = [
        f"{'↑' if t['delta_weight'] > 0 else '↓'}{t['ticker']}"
        f" {format_de(abs(t['delta_weight']) * 100, 1)} %"
        for t in material[:TRADE_NAME_CAP]
    ]
    rest = len(trades) - len(named)
    parts = list(named)
    if rest > 0:
        # "kleine" stays invariant for 1 and n — no singular/plural branch needed.
        parts.append(f"+{rest} kleine")
    return "Trades: " + " · ".join(parts)


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
    alerts_today: list[dict] | None = None,  # noqa: ARG001 - dashboard renders alerts (VoicesPanel)
    opportunities: list[dict] | None = None,
    earnings_this_week: list[dict] | None = None,
    regime: dict | None = None,
    sector_line: str | None = None,
    core_block: str | None = None,
    below_threshold: int | None = None,  # noqa: ARG001 - accepted for callers, no longer rendered
    autodepot: dict | None = None,
    shortterm: list[dict] | None = None,
    dash_url: str | None = None,
    dash_token: str | None = None,
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
    persisted. `core_block` (butler savings-plan block or its one-line stand-in)
    arrives pre-rendered for the same html mode and is appended verbatim.

    v10: `autodepot` (run_digest.collect_autodepot shape) renders the Auto-Depot block —
    the meta depot advances NIGHTLY after US close, so the block is stamped with its own
    as_of date instead of claiming "heute". Omitted entirely when None (no depot yet).

    v11: `shortterm` (run_digest.collect_shortterm shape, one dict per arena lane) renders
    the "⚡ Arena" summary line; omitted when None/empty.

    2026-08-04 (Telegram diet): this is a SIGNAL, not a report — one line per topic, target
    ≤ 16 lines total. Depth is one tap away instead of inlined: with `dash_url` set, every
    section head deep-links into the matching cockpit view. Reference material moved out
    entirely (per-lane test-bench counters, exposure/drawdown, the alert list, the
    below-threshold count) because the dashboard shows it; the evidence hit-rates and the
    earnings calendar only CONDENSE, because no frontend renders them yet. Repeating
    yesterday's open-pitch list was the biggest source of noise — only pitches newer than
    `decided_since` get a line now."""

    def _head(text: str) -> str:
        return f"<b>{escape_html(text)}</b>" if html else text

    def _line(text: str) -> str:
        return escape_html(text) if html else text

    def _link(text: str, view: str) -> str:
        """Section head as a deep link into the phone cockpit's matching view.

        Query param (not a path) because the dashboard is served by StaticFiles at "/" —
        `/depots` would 404, `?view=depots` always resolves to index.html. Plain-text
        mode never links: a bare URL adds noise to the stdout/SMTP rendering.

        With `dash_token` the link carries the shared secret, so a phone whose `es_dash`
        cookie expired does not land on a 401 (Nico 2026-08-05). api.py's middleware
        exchanges `?token=` for the httponly cookie on first load and the frontend strips
        it from the visible URL afterwards. The trade-off is deliberate and one-way: the
        token then sits in the Telegram history, which is server-stored and not
        end-to-end encrypted. It is only ever added in `html` mode — the plain-text
        rendering goes to stdout and copilot.log, where a secret has no business.
        """
        if not (html and dash_url):
            return _head(text)
        target = f"{dash_url.rstrip('/')}/?view={view}"
        if dash_token:
            target += f"&token={dash_token}"
        # escape_html turns the & into &amp;, which is what an HTML attribute needs — a
        # raw & breaks Telegram's parser (see test_dash_url_is_escaped).
        return f'<b><a href="{escape_html(target)}">{escape_html(text)}</a></b>'

    lines = [_head(f"Copilot-Digest {date_label}")]
    if regime is not None:
        lines.append(_line(
            f"{regime['emoji']} Marktlage: {regime['label']}"
            f" ({regime['green_count']}/{regime['available']} Signale grün)"
        ))
    if sector_line is not None:
        lines.append(_line(f"📊 {sector_line}"))
    if core_block is not None:
        # Pre-rendered by butler.render_core_block/core_running_line with the same
        # html flag — appending verbatim keeps escaping in exactly one place.
        lines.append(core_block)
    if autodepot is not None:
        eur = (
            f" ({format_de(autodepot['equity_eur'])} €)"
            if autodepot.get("equity_eur") is not None
            else ""
        )
        day = ""
        if autodepot.get("day_pnl") is not None:
            emoji = "🟢" if autodepot["day_pnl"] >= 0 else "🔴"
            # The day RETURN carries the meaning; the absolute P&L is one tap away in
            # the cockpit. Falls back to the absolute figure when no return was stored.
            move = (
                format_de_pct(autodepot["day_return"])
                if autodepot.get("day_return") is not None
                else f"{format_de(autodepot['day_pnl'])} $"
            )
            day = f" · {emoji} heute {move}"
        lines.append(_link(
            f"🤖 Auto-Depot {format_de(autodepot['equity'])} ${eur}{day}", "depots"
        ))
        if autodepot.get("stale_days"):
            lines.append(_line(
                f"  ⚠️ Stand {autodepot['stale_days']} Handelstage alt — Kette prüfen"
            ))
        lines.append(_line(
            f"  Gesamt {format_de_pct(autodepot['total_return'])}"
            f" vs SPY {format_de_pct(autodepot['benchmark_return'])}"
        ))
        lines.append(_line(f"  {_trade_summary(autodepot.get('trades') or [])}"))
        for detail in autodepot.get("risk_events") or []:
            lines.append(_line(f"  ⚠ {detail}"))
        # A persisting breaker stage acts silently in the engine (no daily event spam) —
        # the digest is where its ongoing grip has to stay visible instead.
        stage_note = {1: "Drawdown-Breaker aktiv: halbes Exposure",
                      2: "Drawdown-Breaker aktiv: komplett Cash"}
        stage = autodepot.get("breaker_stage", 0)
        if stage in stage_note:
            lines.append(_line(f"  ⛔ {stage_note[stage]}"))
    if shortterm:
        best = max(shortterm, key=lambda lane: lane["total_return"])
        day_values = [lane["day_pnl"] for lane in shortterm if lane.get("day_pnl") is not None]
        day_note = ""
        if day_values:
            total_day = sum(day_values)
            # "±0 $" instead of "🟢 +0 $": a zero day is not a green day.
            day_note = (
                " · heute ±0 $" if total_day == 0
                else f" · heute {format_de(total_day)} $"
            )
        lines.append(_link(
            f"⚡ Arena {len(shortterm)} Lanes · beste {best['label']}"
            f" {format_de_pct(best['total_return'])}{day_note}",
            "depots",
        ))
        # Only malfunctions and state CHANGES get their own line — a lane grinding
        # through its test bench does not.
        for lane in shortterm:
            if lane.get("stale_days"):
                lines.append(_line(
                    f"  ⚠ {lane['label']}: {lane['stale_days']} Tage keine Daten"
                ))
            if lane.get("promoted"):
                lines.append(_line(f"  🎓 {lane['label']} verdient jetzt Depot-Kapital"))
            elif (lane.get("promotion") or {}).get("eligible"):
                lines.append(_line(
                    f"  ✅ {lane['label']} hat den Prüfstand bestanden"
                    " — Aufnahme beim nächsten Nightly-Lauf"
                ))
    # Blank line: the market/depot head above, the day's items below. The "📌 Heute
    # aufgefallen" alert list used to sit here — dropped 2026-08-04, it duplicated the
    # chances line and its reasons carried whole press headlines. Alerts stay visible in
    # the dashboard (/api/evidence -> recent_alerts -> VoicesPanel).
    lines.append("")
    if opportunities:
        attractive = []
        for entry in opportunities:
            try:
                verdict = compute_verdict(entry)
            except KeyError:
                # Minimal/pre-v8 watchlist entries can lack "breakdown" — skip the entry
                # instead of crashing the whole digest over one missing field.
                continue
            if verdict["level"] != "red":
                attractive.append(f"{entry['ticker']} {round(entry['composite'] * 100)}")
        if attractive:
            lines.append(_link("🎯 Chancen: " + " · ".join(attractive), "radar"))
        else:
            lines.append(_line(
                "🎯 Keine attraktive Chance heute — Nichtstun ist die richtige Aktion."
            ))
    if earnings_this_week:
        today = [e["ticker"] for e in earnings_this_week if e["earnings_date"] == date_label]
        rest = len(earnings_this_week) - len(today)
        if today:
            lines.append(_line(
                f"📅 Earnings heute: {', '.join(today)} · {rest} weitere diese Woche"
            ))
        else:
            lines.append(_line(f"📅 Earnings: heute keine · {rest} diese Woche"))
    open_pitches = _dedupe_open([p for p in pitches if p["status"] == "open"])
    decided = [
        p for p in pitches
        if p["status"] != "open"
        and (decided_since is None or (p["decided_at"] or "") >= decided_since)
    ]
    if not open_pitches:
        lines.append(_line(
            "📬 Keine offenen Pitches — nichts zu tun ist gerade die richtige Aktion."
        ))
    else:
        fresh = [
            p for p in open_pitches
            if decided_since is None or p["created_at"] >= decided_since
        ]
        # "N Pitch(es) offen" carries the count so no singular/plural agreement is needed;
        # only FRESH pitches get a line — repeating yesterday's identical list every day
        # is what made the digest a wall of text (Nico, 2026-08-04).
        noun = "Pitch" if len(open_pitches) == 1 else "Pitches"
        suffix = f"{len(fresh)} neu" if fresh else "nichts neu"
        lines.append(_link(f"📬 {len(open_pitches)} {noun} offen · {suffix}", "inbox"))
        for p in fresh[:OPEN_PITCH_CAP]:
            # v9: the same verdict already persisted on the pitch at notify time
            # (pitch.compute_verdict, see inbox_storage) — "📬" is only the honest
            # fallback for pre-v8 rows that never had a verdict computed/stored.
            icon = VERDICT_EMOJI.get(p.get("verdict"), "📬")
            lines.append(_line(
                f"  {icon} {p['ticker']} · {round(p['composite'] * 100)}/100"
                f" · {p['price']:.2f}"
            ))
    if decided:
        lines.append(_line(
            "✅ Entschieden: " + " · ".join(
                f"{_STATUS_ICON.get(p['status'], p['status'])} {p['ticker']}"
                for p in decided
            )
        ))
    if evidence_stats:
        resolved = sum(entry["n_resolved"] for entry in evidence_stats.values())
        open_count = sum(entry["n_open"] for entry in evidence_stats.values())
        if resolved == 0:
            lines.append(_line(
                f"🔬 Evidenz: {format_de(open_count)} offen, noch keine Auflösung"
            ))
        else:
            best = max(
                (item for item in evidence_stats.items() if item[1]["n_resolved"] > 0),
                key=lambda item: item[1]["hit_rate"],
            )
            lines.append(_line(
                f"🔬 Evidenz: {format_de(resolved)} aufgelöst · beste Quelle"
                f" {_SOURCE_LABEL.get(best[0], best[0])}"
                f" {round(best[1]['hit_rate'] * 100)} %"
            ))
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


def build_proof_report(books: list[dict], *, month_label: str, html: bool = False) -> str:
    """Monthly proof summary (v12 P3): one compact card per book, verdict first.
    Metrics the track record cannot support yet render as "—" — never invented."""
    def head(text: str) -> str:
        return f"<b>{text}</b>" if html else text

    def fmt(value, digits=2, suffix=""):  # noqa: ANN001, ANN202
        return "—" if value is None else f"{value:,.{digits}f}{suffix}"

    lines = [head(f"🧾 Monats-Beweisbericht — {month_label}")]
    for book in books:
        lines.append("")
        lines.append(head(book["label"]))
        lines.append(f"  {book['verdict_label']}")
        lines.append(
            f"  Gesamt {fmt(book['total_return_pct'], 1, ' %')}"
            f" · Sharpe {fmt(book['sharpe_annualised'])}"
            f" · Max-DD {fmt(book['max_drawdown_pct'], 1, ' %')}"
        )
        extra = []
        if book["realized_win_rate"] is not None:
            extra.append(f"Trefferquote {book['realized_win_rate'] * 100:.0f} %")
        if book["cost_share_of_pnl"] is not None:
            extra.append(f"Kostenanteil {book['cost_share_of_pnl'] * 100:.0f} %")
        if extra:
            lines.append("  " + " · ".join(extra))
    lines.append("")
    lines.append("Gemessen, nicht versprochen — Details im Dashboard-Tab „Beweis\u201c.")
    return "\n".join(lines)
