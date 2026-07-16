"""Plain-German pitch text for one watchlist entry.

Beginner-readable layout: a header, two interpretive LLM sentences (what the
company does / why now), a 0–100 entry score with a plain band word, a concrete
tranche scale-in plan, key figures (KGV), and a THIRD-PARTY analyst-consensus
target — labelled as such, with an honest "keine Schätzung verfügbar" when the
free data has no coverage; NEVER a self-invented forecast.

The LLM (local Ollama via chat.ask_ollama) only INTERPRETS the computed numbers
(same guardrail as analysis.py / chat.py). Any failure degrades to a deterministic
fallback marked with PITCH_LLM_UNAVAILABLE_PREFIX; the structured sections below
the prose are deterministic and survive an LLM outage. Missing Ollama never blocks
a notification.
"""
from __future__ import annotations

from collections.abc import Callable

from equity_scout.chat import ChatError, ask_ollama
from equity_scout.constants import SHORT_DISCLAIMER
from equity_scout.evidence.aggregate import evidence_block, evidence_summary_lines
from equity_scout.fundamentals import Fundamentals
from equity_scout.telegram_client import escape_html, strip_html

# Telegram photo captions cap at 1024 UTF-16 code units; headroom for emoji + edits.
_CAPTION_LIMIT = 980

PITCH_LLM_UNAVAILABLE_PREFIX = "(Automatische Kurzeinschätzung nicht verfügbar)"
# Telegram's 4096 hard limit counts UTF-16 code units, not Python chars; the 96-unit
# headroom absorbs astral-plane emoji (2 units each) plus the decision edit suffix.
_LIMIT = 4000

_QUESTION = (
    "Fasse in maximal zwei deutschen Sätzen zusammen, was dieses Unternehmen macht und "
    "warum der aktuelle Kurs laut den Kennzahlen unten in einer Einstiegszone liegt, "
    "und nenne genau ein wesentliches Risiko. "
    "Keine Prognosen, keine Kursziele, keine Empfehlung — nur Einordnung der Zahlen."
)


def _ask_default(question: str, context: str) -> str:
    return ask_ollama(question, context)


def _fact_block(entry: dict) -> str:
    """Compact fact context fed to the LLM so it can interpret (not forecast) the numbers."""
    breakdown = entry["breakdown"]
    lines = [
        f"Score {round(entry['composite'] * 100)}/100 · Bucket: {entry['bucket']}",
        "Stile: " + " · ".join(
            f"{label} {breakdown.get(key, 0.0) * 100:.0f}"
            for key, label in (
                ("value", "Value"), ("quality", "Quality"),
                ("momentum", "Momentum"), ("growth", "Growth"),
            )
        ),
        f"Kurs {entry['price']:.2f} · Zone {entry['entry_zone_low']:.2f}–"
        f"{entry['entry_zone_high']:.2f}",
        entry["zone_note"],
    ]
    for reading in entry["readings"]:
        lines.append(f"• {reading['reason']}")
    return "\n".join(lines)


def _interpretation(entry: dict, ask: Callable[[str, str], str]) -> str:
    """Two interpretive sentences from the LLM, or a deterministic fallback line."""
    try:
        return ask(_QUESTION, _fact_block(entry)).strip()
    except ChatError:
        detail = (
            "Kennzahlen und Risiko siehe unten."
            if entry["readings"]
            else "Keine Signaldetails verfügbar."
        )
        return f"{PITCH_LLM_UNAVAILABLE_PREFIX} — {detail}"


# v8 at-a-glance verdict: a three-band judgement of ENTRY ATTRACTIVENESS per the model —
# never a price forecast. Bands align with _score_line's (<40 / 40–70 / >=70); a very weak
# sub-signal (weakest reading below _WEAK_SIGNAL) downgrades one level so a shiny composite
# cannot hide a broken input.
_VERDICT_LEVELS = {
    "green": ("🟢", "Einstieg attraktiv"),
    "yellow": ("🟡", "Einstieg neutral"),
    "red": ("🔴", "Einstieg schwach"),
}
_WEAK_SIGNAL = 0.2


def compute_verdict(entry: dict) -> dict:
    """{"level", "emoji", "label", "why"} — deterministic and JSON-ready, so the same
    verdict renders identically on Telegram, the inbox API, and the dashboard."""
    score = round(entry["composite"] * 100)
    level = "red" if score < 40 else "yellow" if score < 70 else "green"
    readings = entry.get("readings") or []
    weakest = min(readings, key=lambda r: r["score"]) if readings else None
    if weakest is not None and weakest["score"] < _WEAK_SIGNAL and level != "red":
        level = {"green": "yellow", "yellow": "red"}[level]
        why = f"Score {score}/100, aber gebremst — {weakest['reason']}"
    elif level == "green":
        why = f"Starke Signale laut Modell: {_top_factors(entry['breakdown'])}"
    elif level == "yellow":
        why = f"Gemischtes Bild laut Modell — stärkste Signale: {_top_factors(entry['breakdown'])}"
    else:
        why = f"Schwache Signale laut Modell (Score {score}/100)"
    emoji, label = _VERDICT_LEVELS[level]
    return {"level": level, "emoji": emoji, "label": label, "why": why}


def _score_line(entry: dict) -> str:
    score = round(entry["composite"] * 100)
    band = "niedrig" if score < 40 else "mittel" if score < 70 else "hoch"
    return (
        f"Einstiegs-Score: {score}/100 ({band}) — wie attraktiv der Einstieg gerade ist, "
        "kein Kursversprechen."
    )


def _tranche_block(entry: dict, cur: str) -> str | None:
    """Scale-in reference plan from the entry's dip tranches — buy levels, not a prediction."""
    tranches = entry.get("tranches", [])
    if not tranches:
        return None
    lines = [f"So könntest du einsteigen — in {len(tranches)} Schritten:"]
    for tranche in tranches:
        price = tranche.get("trigger_price")
        if price is None:
            lines.append(f"• {tranche['label']}: zeitlich gestaffelt")
        else:
            lines.append(f"• {tranche['label']}: bei ~{price:.2f}{cur}")
    lines.append("Nicht alles auf einmal — in Schritten kaufen glättet den Einstiegspreis.")
    return "\n".join(lines)


def _kennzahlen_block(entry: dict, fundamentals: Fundamentals | None) -> str:
    lines = ["Kennzahlen:"]
    if fundamentals is not None and fundamentals.trailing_pe is not None:
        lines.append(
            f"• KGV {fundamentals.trailing_pe:.0f} — Kurs-Gewinn-Verhältnis; grob "
            "„wie viele Jahresgewinne kostet die Aktie“, niedriger = günstiger bewertet."
        )
    lines.append(f"• {entry['zone_note']}")
    # Since the intraday chain (v6 P5) pitches DURING the trading day, the price basis must be
    # honest on every pitch: yfinance quotes lag roughly 15 minutes.
    lines.append("• Kursbasis yfinance, ca. 15 Minuten verzögert — kein Echtzeitkurs.")
    return "\n".join(lines)


def _analyst_line(entry: dict, fundamentals: Fundamentals | None, cur: str) -> str:
    """Third-party sell-side consensus target — labelled as such — or an honest absence.
    NEVER computes or guesses a target when the data has no coverage."""
    target = fundamentals.analyst_target if fundamentals else None
    count = fundamentals.analyst_count if fundamentals else None
    if target is None or count is None:
        return "Analystensicht: keine Schätzung verfügbar (bei kleineren/nicht-US-Werten normal)."
    line = f"Analystensicht: Ø-Kursziel {target:.2f}{cur} ({count} Schätzungen)"
    price = entry["price"]
    if price > 0:
        upside = (target / price - 1.0) * 100
        line += f" → {upside:+.0f} % zum aktuellen Kurs"
    return f"{line}. Fremde Analystenmeinungen, oft falsch — keine Garantie."


def _fscore_band(score: int) -> str:
    return "stark" if score >= 7 else "solide" if score >= 5 else "schwach"


def _fscore_line(f_score: dict | None) -> str | None:
    """Balance-trend annotation from official SEC numbers (fscore.py). Deliberately a
    standalone label — it does NOT feed the composite (watchlist-only data cannot be
    ranked against the whole universe honestly). Omitted when absent (non-US name,
    EDGAR unconfigured, or too few evaluable criteria)."""
    if f_score is None:
        return None
    return (
        f"Bilanz-Trend (Piotroski F-Score): {f_score['score']}/9 —"
        f" {_fscore_band(f_score['score'])}"
        f" ({f_score['evaluable']} von 9 Kriterien bewertbar, Geschäftsjahr"
        f" {f_score['fiscal_year']}, Quelle: offizielle SEC-Zahlen)."
        " Ohne Einfluss auf den Score oben."
    )


def _risk_line(entry: dict) -> str | None:
    """Deterministic risk proxy: the weakest sub-signal's reason (ties: first) — computed."""
    readings = entry["readings"]
    if not readings:
        return None
    weakest = min(readings, key=lambda r: r["score"])
    return f"Risiko: {weakest['reason']}"


def _target_stop_line(target_stop: dict | None, cur: str) -> str:
    """A4's deterministic model target/stop (`entry.compute_target_stop`, the `entry_tb`
    champion's OWN vol-scaled barrier config) — NOT the third-party analyst consensus above
    and NOT the rule-based entry zone in `_kennzahlen_block`'s `zone_note`. The "Kursziel"
    label keeps it unambiguous even though both this line and the entry zone use 🎯.
    Honest gap (never a guess) when there is no champion / barrier config / long-enough
    history, same idiom as `_analyst_line`'s absence branch."""
    if target_stop is None:
        return (
            "🎯 Kursziel: kein Modell-Kursziel verfügbar "
            "(kein trainiertes Modell oder zu kurze Kurshistorie)."
        )
    horizon = target_stop["horizon_days"]
    return (
        f"🎯 Kursziel {target_stop['target']:.2f}{cur} · 🛑 Stop {target_stop['stop']:.2f}{cur} "
        f"— Modellschätzung über {horizon} Handelstage, kein Analystenziel, keine Garantie."
    )


def _detail_blocks(
    entry: dict,
    fundamentals: Fundamentals | None,
    evidence: list[dict] | None,
    target_stop: dict | None,
    cur: str,
    f_score: dict | None = None,
) -> list[str]:
    """The read-more depth: everything between the verdict/score head and the risk line.
    The HTML variant folds exactly these blocks into one expandable quote."""
    blocks = [
        _tranche_block(entry, cur),
        _kennzahlen_block(entry, fundamentals),
        _fscore_line(f_score),
        # External evidence annotates the pitch; it has no influence on the composite
        # or the selection above — see evidence/aggregate.py for the delay honesty note.
        evidence_block(evidence) if evidence else None,
        _analyst_line(entry, fundamentals, cur),
        _target_stop_line(target_stop, cur),
    ]
    return [block for block in blocks if block]


def _structured_body(
    entry: dict,
    fundamentals: Fundamentals | None,
    evidence: list[dict] | None,
    target_stop: dict | None,
    f_score: dict | None = None,
) -> str:
    cur = f" {fundamentals.currency}" if fundamentals and fundamentals.currency else ""
    verdict = compute_verdict(entry)
    blocks = [
        f"{verdict['emoji']} {verdict['label']} — {verdict['why']}.",
        _score_line(entry),
        *_detail_blocks(entry, fundamentals, evidence, target_stop, cur, f_score),
        _risk_line(entry),
    ]
    return "\n\n".join(block for block in blocks if block)


def _top_factors(breakdown: dict, n: int = 2) -> str:
    labels = {"value": "Value", "quality": "Quality", "momentum": "Momentum",
              "growth": "Growth", "low_vol": "Low-Vol"}
    ranked = sorted(
        ((labels.get(k, k), v) for k, v in breakdown.items() if k in labels),
        key=lambda kv: kv[1], reverse=True,
    )
    return ", ".join(f"{label} {value * 100:.0f}" for label, value in ranked[:n])


def build_pitch_caption(
    entry: dict,
    fundamentals: Fundamentals | None = None,
    evidence: list[dict] | None = None,
    one_year_return: float | None = None,
    eur_price: float | None = None,
    press_lines: list[str] | None = None,
    target_stop: dict | None = None,
    f_score: dict | None = None,
) -> str:
    """Compact, sectioned caption for the chart-photo pitch. v8 layout: Telegram HTML
    (send with parse_mode="HTML") in four paragraph blocks separated by blank lines —
    head (who + at-a-glance verdict, bold), numbers, context (evidence/press), risk —
    so the caption reads as structured paragraphs instead of a wall of lines (Nico
    2026-07-16). Only <b> is used: photo captions support inline formatting, while the
    expandable quote is reserved for the long TEXT pitch. All dynamic content is
    escaped. Hard-capped for Telegram's 1024-unit photo-caption limit; an over-long
    caption degrades to stripped plain text before cutting so no tag is ever severed.
    `eur_price` rides along for non-EUR listings; `press_lines` are third-party
    headlines (see press.py) — quoted, never interpreted. `target_stop` is A4's
    deterministic model target/stop (`entry.compute_target_stop`); unlike the other
    optional lines it is omitted (not shown as an absence) when None."""
    cur = f" {fundamentals.currency}" if fundamentals and fundamentals.currency else ""
    score = round(entry["composite"] * 100)
    price = f"Kurs {entry['price']:.2f}{cur}"
    if eur_price is not None:
        price += f" (≈ {eur_price:.2f} €)"
    price_bits = [price]
    if fundamentals is not None and fundamentals.trailing_pe is not None:
        price_bits.insert(0, f"KGV {fundamentals.trailing_pe:.0f}")
    if one_year_return is not None:
        price_bits.append(f"1 Jahr {one_year_return * 100:+.0f} %")
    verdict = compute_verdict(entry)
    head = [
        f"<b>📈 {entry['ticker']} — {escape_html(entry['name'])}</b>",
        f"{verdict['emoji']} <b>{verdict['label']}</b> · Score {score}/100 · "
        f"stark: {_top_factors(entry['breakdown'])}",
    ]
    numbers = [
        "💰 " + " · ".join(price_bits),
        f"🎯 Zone {entry['entry_zone_low']:.2f}–{entry['entry_zone_high']:.2f}{cur}",
    ]
    if target_stop is not None:
        # Distinct label ("Kursziel" vs "Zone" right after the shared 🎯) keeps the
        # model target from being read as the entry zone above.
        numbers.append(
            f"🎯 Kursziel {target_stop['target']:.2f}{cur} · "
            f"🛑 Stop {target_stop['stop']:.2f}{cur}"
        )
    target = fundamentals.analyst_target if fundamentals else None
    if target is not None and entry["price"] > 0:
        upside = (target / entry["price"] - 1.0) * 100
        numbers.append(f"🔭 Analysten-Ø-Ziel {target:.2f}{cur} ({upside:+.0f} %) — fremde Meinung")
    if f_score is not None:
        numbers.append(f"📒 Bilanz-Trend {f_score['score']}/9 ({_fscore_band(f_score['score'])})")
    context = [
        f"👥 {escape_html(evidence_line)}"
        for evidence_line in evidence_summary_lines(evidence or [])
    ]
    context += [f"🗞️ {escape_html(press_line)}" for press_line in press_lines or []]
    risk = _risk_line(entry)
    risk_block = [f"⚠️ {escape_html(risk if len(risk) <= 90 else risk[:89] + '…')}"] if risk else []
    blocks = ["\n".join(block) for block in (head, numbers, context, risk_block) if block]
    caption = "\n\n".join(blocks)
    if len(caption) <= _CAPTION_LIMIT:
        return caption
    plain = strip_html(caption)
    return plain if len(plain) <= _CAPTION_LIMIT else plain[: _CAPTION_LIMIT - 1] + "…"


def _build_pitch_html(
    entry: dict,
    fundamentals: Fundamentals | None,
    ask: Callable[[str, str], str],
    evidence: list[dict] | None,
    target_stop: dict | None,
    f_score: dict | None = None,
) -> str:
    """v8 Telegram HTML variant: bold head + verdict and the interpretive prose stay
    visible; the full detail depth (tranches, Kennzahlen, evidence, analyst, target)
    folds into ONE <blockquote expandable> — supported in text messages, which is the
    only place this variant is sent (the photo caption deliberately never uses it).
    Same honesty frame as the plain variant: risk line + disclaimer always visible."""
    cur = f" {fundamentals.currency}" if fundamentals and fundamentals.currency else ""
    verdict = compute_verdict(entry)
    details = _detail_blocks(entry, fundamentals, evidence, target_stop, cur, f_score)
    risk = _risk_line(entry)
    head = (
        f"<b>📈 {entry['ticker']} — {escape_html(entry['name'])}</b>\n"
        f"{verdict['emoji']} <b>{verdict['label']}</b> — {escape_html(verdict['why'])}."
    )

    def assemble(detail_raw: str, prose: str) -> str:
        parts = [
            head,
            prose,
            escape_html(_score_line(entry)),
            f"<blockquote expandable>{escape_html(detail_raw)}</blockquote>"
            if detail_raw
            else None,
            f"⚠️ {escape_html(risk)}" if risk else None,
            SHORT_DISCLAIMER,
        ]
        return "\n\n".join(part for part in parts if part)

    detail_raw = "\n\n".join(details)
    prose_budget = _LIMIT - len(assemble(detail_raw, ""))
    prose = escape_html(_interpretation(entry, ask))
    if len(prose) > prose_budget:
        prose = prose[: prose_budget - 1] + "…" if prose_budget > 1 else ""
    text = assemble(detail_raw, prose)
    overflow = len(text) - _LIMIT
    if overflow > 0 and detail_raw:
        # Cut the RAW detail before escaping (never sever an &amp;-entity), then rebuild.
        # Removing N raw chars removes at least N escaped chars, so one pass suffices.
        detail_raw = detail_raw[: max(len(detail_raw) - overflow - 1, 0)] + "…"
        text = assemble(detail_raw, prose)
    if len(text) > _LIMIT:  # pathological (oversized name): strip tags, keep disclaimer
        plain = strip_html(text)
        room = max(_LIMIT - len(SHORT_DISCLAIMER) - 3, 0)
        text = f"{plain[:room]}…\n\n{SHORT_DISCLAIMER}"
    return text


def build_pitch(
    entry: dict,
    fundamentals: Fundamentals | None = None,
    ask: Callable[[str, str], str] = _ask_default,
    evidence: list[dict] | None = None,
    target_stop: dict | None = None,
    html: bool = False,
    f_score: dict | None = None,
) -> str:
    """Header + LLM interpretation (or fallback) + deterministic structured sections.
    `target_stop` is A4's deterministic model target/stop (`entry.compute_target_stop`) —
    see `_target_stop_line` for how it stays distinct from the analyst consensus and the
    rule-based entry zone. `html=True` renders the Telegram HTML variant (expandable
    detail block); the plain default stays the dashboard-inbox rendering. `f_score`
    (fscore.load_f_score shape) adds the standalone balance-trend line."""
    if html:
        return _build_pitch_html(entry, fundamentals, ask, evidence, target_stop, f_score)
    header = f"📈 {entry['ticker']} — {entry['name']}"
    prose = _interpretation(entry, ask)
    body = _structured_body(entry, fundamentals, evidence, target_stop, f_score)
    # Header + structured body + disclaimer form the frame that must survive truncation;
    # the interpretive LLM prose is cut first, so a shortened message stays honest + intact.
    # separators: header\n prose \n\n body \n\n disclaimer = 5 chars.
    prose_budget = _LIMIT - len(header) - len(body) - len(SHORT_DISCLAIMER) - 5
    if len(prose) > prose_budget:
        prose = prose[: prose_budget - 1] + "…" if prose_budget > 1 else ""
    top = f"{header}\n{prose}" if prose else header
    text = f"{top}\n\n{body}\n\n{SHORT_DISCLAIMER}"
    if len(text) > _LIMIT:  # pathological: body alone over budget — keep header + disclaimer
        head, tail = f"{header}\n", f"\n\n{SHORT_DISCLAIMER}"
        room = max(_LIMIT - len(head) - len(tail) - 1, 0)
        text = head + body[:room] + "…" + tail
    return text
