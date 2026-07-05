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
from equity_scout.fundamentals import Fundamentals

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


def _structured_body(entry: dict, fundamentals: Fundamentals | None) -> str:
    cur = f" {fundamentals.currency}" if fundamentals and fundamentals.currency else ""
    blocks = [
        _score_line(entry),
        _tranche_block(entry, cur),
        _kennzahlen_block(entry, fundamentals),
        _analyst_line(entry, fundamentals, cur),
        _risk_line(entry),
    ]
    return "\n\n".join(block for block in blocks if block)


def build_pitch(
    entry: dict,
    fundamentals: Fundamentals | None = None,
    ask: Callable[[str, str], str] = _ask_default,
) -> str:
    """Header + LLM interpretation (or fallback) + deterministic structured sections."""
    header = f"📈 {entry['ticker']} — {entry['name']}"
    prose = _interpretation(entry, ask)
    body = _structured_body(entry, fundamentals)
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
