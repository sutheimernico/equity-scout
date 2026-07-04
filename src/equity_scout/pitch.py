"""German pitch text for one watchlist entry.

The LLM (local Ollama via chat.ask_ollama) INTERPRETS the computed numbers into
two readable sentences — it must never forecast or rank (same guardrail as
analysis.py / chat.py). Every failure degrades to a deterministic fallback built
from the sub-signal reasons, marked with PITCH_LLM_UNAVAILABLE_PREFIX (mirrors
analysis.THESIS_UNAVAILABLE_PREFIX): missing Ollama never blocks a notification.
"""
from __future__ import annotations

from collections.abc import Callable

from equity_scout.chat import ChatError, ask_ollama

PITCH_LLM_UNAVAILABLE_PREFIX = "(Automatische Kurzeinschätzung nicht verfügbar)"
_LIMIT = 4000  # Telegram hard limit 4096; keep headroom for the decision edit suffix

_QUESTION = (
    "Fasse in maximal zwei deutschen Sätzen zusammen, was dieses Unternehmen macht und "
    "warum der aktuelle Kurs laut den Kennzahlen unten in einer Einstiegszone liegt. "
    "Keine Prognosen, keine Kursziele, keine Empfehlung — nur Einordnung der Zahlen."
)


def _ask_default(question: str, context: str) -> str:
    return ask_ollama(question, context)


def _fact_block(entry: dict) -> str:
    lines = [
        f"Score {round(entry['composite'] * 100)}/100 · Bucket: {entry['bucket']}",
        f"Kurs {entry['price']:.2f} · Zone {entry['entry_zone_low']:.2f}–"
        f"{entry['entry_zone_high']:.2f}",
        entry["zone_note"],
    ]
    for reading in entry["readings"]:
        lines.append(f"• {reading['reason']}")
    return "\n".join(lines)


def build_pitch(entry: dict, ask: Callable[[str, str], str] = _ask_default) -> str:
    """Header + LLM interpretation (or fallback) + fact block + disclaimer."""
    header = f"📈 {entry['ticker']} — {entry['name']}"
    facts = _fact_block(entry)
    try:
        summary = ask(_QUESTION, facts).strip()
    except ChatError:
        summary = f"{PITCH_LLM_UNAVAILABLE_PREFIX} — Signalgründe siehe unten."
    text = f"{header}\n\n{summary}\n\n{facts}\n\nKeine Anlageberatung."
    if len(text) > _LIMIT:
        text = text[: _LIMIT - 1] + "…"
    return text
