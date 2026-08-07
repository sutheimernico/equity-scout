"""Deterministic retrieval in front of the local chat LLM.

The 2026-08-07 measurement (docs/research/2026-08-07-assistant-measurement.md) showed the
model hallucinating whenever the static context missed the asked-about data, and advising
when it should refuse. Everything in this module is therefore deterministic and testable:
the LLM only ever interprets facts this code selected — it never selects facts itself.
"""
from __future__ import annotations

import re

# "Soll ich X kaufen?" in its German variants. Questions about THIRD-PARTY buys
# ("Wer hat Intel gekauft?") must NOT match — the pattern requires an advice frame
# (soll/würdest/lohnt/kann ich) before the trade verb, not the verb alone.
_ADVICE_RE = re.compile(
    r"(soll(te)?\s+ich|w[üu]rdest\s+du|lohnt\s+(es\s+)?sich|kann\s+ich)"
    r".{0,60}?(kaufen|verkaufen|einsteigen|aussteigen|investieren)",
    re.IGNORECASE | re.DOTALL,
)


def is_advice_question(question: str) -> bool:
    """True when the question asks for buy/sell advice — answered by a fixed sentence
    WITHOUT the LLM (see chat.REFUSAL_ANSWER); a 7B model cannot be trusted to refuse."""
    return bool(_ADVICE_RE.search(question))
