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


def _risk_line(entry: dict) -> str | None:
    """Deterministic risk proxy: the weakest sub-signal's reason (ties: first) — computed."""
    readings = entry["readings"]
    if not readings:
        return None
    weakest = min(readings, key=lambda r: r["score"])
    return f"Risiko: {weakest['reason']}"


def _structured_body(
    entry: dict, fundamentals: Fundamentals | None, evidence: list[dict] | None
) -> str:
    cur = f" {fundamentals.currency}" if fundamentals and fundamentals.currency else ""
    blocks = [
        _score_line(entry),
        _tranche_block(entry, cur),
        _kennzahlen_block(entry, fundamentals),
        # External evidence annotates the pitch; it has no influence on the composite
        # or the selection above — see evidence/aggregate.py for the delay honesty note.
        evidence_block(evidence) if evidence else None,
        _analyst_line(entry, fundamentals, cur),
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
) -> str:
    """Compact, sectioned caption for the chart-photo pitch (Nico 2026-07-15: the long
    pitch was unübersichtlich; disclaimer/delay footer removed on his call same day).
    One fact per line, hard-capped for Telegram's 1024-unit photo-caption limit; the
    chart itself carries the price history. The long `build_pitch` text stays the
    dashboard-inbox version. `eur_price` rides along for non-EUR listings; `press_lines`
    are third-party headlines (see press.py) — quoted, never interpreted."""
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
    lines = [
        f"📈 {entry['ticker']} — {entry['name']}",
        f"🧮 Score {score}/100 · stark: {_top_factors(entry['breakdown'])}",
        "💰 " + " · ".join(price_bits),
        f"🎯 Zone {entry['entry_zone_low']:.2f}–{entry['entry_zone_high']:.2f}{cur}",
    ]
    target = fundamentals.analyst_target if fundamentals else None
    if target is not None and entry["price"] > 0:
        upside = (target / entry["price"] - 1.0) * 100
        lines.append(f"🔭 Analysten-Ø-Ziel {target:.2f}{cur} ({upside:+.0f} %) — fremde Meinung")
    for evidence_line in evidence_summary_lines(evidence or []):
        lines.append(f"👥 {evidence_line}")
    for press_line in press_lines or []:
        lines.append(f"🗞️ {press_line}")
    risk = _risk_line(entry)
    if risk:
        lines.append(f"⚠️ {risk if len(risk) <= 90 else risk[:89] + '…'}")
    caption = "\n".join(lines)
    return caption if len(caption) <= _CAPTION_LIMIT else caption[: _CAPTION_LIMIT - 1] + "…"


def build_pitch(
    entry: dict,
    fundamentals: Fundamentals | None = None,
    ask: Callable[[str, str], str] = _ask_default,
    evidence: list[dict] | None = None,
) -> str:
    """Header + LLM interpretation (or fallback) + deterministic structured sections."""
    header = f"📈 {entry['ticker']} — {entry['name']}"
    prose = _interpretation(entry, ask)
    body = _structured_body(entry, fundamentals, evidence)
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
