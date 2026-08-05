"""Pure logic for the phone card's AI texts and its 1-year sparkline.

Two jobs, both deterministic and offline-testable:

1. Prompts + cleaning for the two LLM texts the card shows — one sentence on what the
   company does, and a short summary of its recent headlines. The LLM only ever
   INTERPRETS text and numbers it is handed (same guardrail as pitch.py / chat.py):
   no forecasts, no price targets, no recommendation. Whatever it returns is cleaned
   hard, because a local 7B model reliably adds preambles, markdown and bullets that
   have no room on a phone card.

2. Reducing a year of daily closes to a sparkline-sized series. First and last close
   survive downsampling exactly, because the card derives the 1-year return from those
   two endpoints — a smoothed endpoint would print a return the stock never had.

The network (Ollama, news feeds, yfinance) lives in scripts/run_insights.py; the SQLite
side lives in insights_storage.py. This module imports neither.
"""
from __future__ import annotations

import re
from datetime import datetime

# Sentence budgets. The card shows these on a 390 px screen: one line of business, a
# short paragraph of news. Longer text is not more informative, it is just scrolled past.
BUSINESS_MAX_CHARS = 180
NEWS_MAX_CHARS = 320

BUSINESS_QUESTION = (
    "Erklaere in genau EINEM deutschen Satz, womit dieses Unternehmen sein Geld verdient. "
    "Keine Prognose, kein Kursziel, keine Empfehlung, kein Bezug auf den Aktienkurs. "
    "Antworte nur mit dem Satz selbst, ohne Einleitung."
)

NEWS_QUESTION = (
    "Fasse die unten numerierten Schlagzeilen in maximal zwei deutschen Saetzen zusammen: "
    "worum geht es bei diesem Unternehmen aktuell? Nenne nur, was in den Schlagzeilen steht. "
    "Keine Prognose, kein Kursziel, keine Empfehlung. "
    "Wenn unten keine Schlagzeilen stehen, antworte genau: keine aktuellen Schlagzeilen. "
    "Antworte nur mit der Zusammenfassung selbst, ohne Einleitung."
)

# A 7B model announces itself before answering. These are the openers observed in
# practice; the pattern is anchored at the start and only fires when a colon follows,
# so a legitimate sentence containing "Zusammenfassung" survives.
_PREAMBLE = re.compile(
    r"^\s*(hier (ist|kommt|w[äa]re)[^:]{0,40}|zusammenfassung|antwort|kurzfassung|"
    r"sicher|gerne|nat[üu]rlich)\s*:\s*",
    re.IGNORECASE,
)
_MARKDOWN = re.compile(r"[*_`#]+")
_BULLET = re.compile(r"^\s*[-•–]\s*", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def clean_llm_text(raw: str, *, max_chars: int = BUSINESS_MAX_CHARS) -> str | None:
    """Card-ready text from a raw local-LLM answer, or None when there is nothing left.

    Truncation prefers a sentence boundary: a card that ends mid-clause reads like a bug.
    Only when the very first sentence already exceeds the budget does it hard-cut with an
    ellipsis, which is honest about being cut off.
    """
    text = _MARKDOWN.sub("", raw or "")
    text = _BULLET.sub("", text)
    # Collapse the model's line breaks: the card is a flowing paragraph, not a list.
    text = " ".join(part.strip() for part in text.splitlines() if part.strip())
    text = _PREAMBLE.sub("", text).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text

    kept: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        candidate = " ".join([*kept, sentence])
        if kept and len(candidate) > max_chars:
            break
        kept.append(sentence)
    joined = " ".join(kept).strip()
    if joined and len(joined) <= max_chars:
        return joined
    return text[:max_chars].rstrip() + "…"


def fact_context(
    *,
    ticker: str,
    name: str,
    sector: str | None,
    industry: str | None,
    price: float,
    currency: str | None,
) -> str:
    """Context for the business sentence: identity and classification only.

    Deliberately WITHOUT the entry zone or the score — this sentence must describe the
    company, and a model handed a verdict starts arguing the verdict.
    """
    lines = [f"Unternehmen: {name} ({ticker})"]
    classification = " / ".join(part for part in (sector, industry) if part)
    if classification:
        lines.append(f"Branche: {classification}")
    lines.append(f"Letzter Kurs: {price:.2f} {currency or ''}".strip())
    return "\n".join(lines)


def news_context(headlines: list[str]) -> str:
    """Numbered headlines as LLM context, or "" when there are none.

    Numbering is not decoration: it lets the summary be traced back to the exact
    headline that caused a claim, and the stored row keeps the same list.
    """
    if not headlines:
        return ""
    return "\n".join(f"{i}. {title}" for i, title in enumerate(headlines, start=1))


def downsample_closes(
    dates: list[datetime], closes: list[float], *, points: int = 60
) -> dict:
    """Reduce a 1-year daily series to `points` samples for the phone sparkline.

    Even index stepping (not averaging): the card draws a price line, and an averaged
    line hides the very drawdowns the shape is there to show. First and last close are
    always the real ones, so the rendered 1-year return matches reality.
    """
    if not closes or not dates:
        raise ValueError("cannot downsample an empty series")
    if len(closes) <= points:
        sampled = list(closes)
    else:
        step = (len(closes) - 1) / (points - 1)
        sampled = [closes[round(i * step)] for i in range(points)]
        sampled[0], sampled[-1] = closes[0], closes[-1]
    return {
        "first_date": dates[0].date().isoformat(),
        "last_date": dates[-1].date().isoformat(),
        "closes": sampled,
    }
