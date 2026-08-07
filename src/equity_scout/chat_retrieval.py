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


# Legal-form suffixes stripped for matching (mirrors frontend/src/company.ts, kept tiny —
# only what the run_scores names actually carry). The leading [\s,]+ is load-bearing: the
# suffix must be its OWN word, otherwise "Visa" loses its tail to `s.a.` and "Cisco" to `co`.
_NAME_SUFFIX_RE = re.compile(
    r"[\s,]+(inc|corp(oration)?|co|ltd|plc|s\.?a\.?|n\.?v\.?|a\.?g\.?|holdings?|"
    r"group|company|common stock|class [a-c])\.?\s*$",
    re.IGNORECASE,
)

# Words of a question, keeping ticker punctuation intact ("ITC.NS", "PETR4.SA", "BRK-B").
# Trailing dots/hyphens are sentence punctuation and get stripped after the split.
_WORD_RE = re.compile(r"[0-9A-Za-zÄÖÜäöüß][0-9A-Za-zÄÖÜäöüß.\-]*")

# How many words a company name may span in the lookup index. Three covers
# "Taiwan Semiconductor Manufacturing" without indexing whole sentences.
_MAX_NAME_WORDS = 3


def short_company_name(name: str) -> str:
    """Company name without its legal-form tail: "Yamato Holdings Co., Ltd." -> "Yamato".

    Iterative because the tails stack — one pass would leave "Yamato Holdings" behind.
    """
    short = name.strip()
    while True:
        stripped = _NAME_SUFFIX_RE.sub("", short).strip()
        if stripped == short:
            return short
        short = stripped


def _words(text: str) -> list[str]:
    return [w.strip(".-") for w in _WORD_RE.findall(text)]


def build_lookup(lexicon: dict[str, str]) -> dict[str, str]:
    """key (lowercased symbol or name prefix) -> ticker.

    Built from the question side, not scanned name by name: with ~7 800 screened titles a
    per-name regex sweep would run 15 000 searches per question. Indexing name PREFIXES
    ("micron", "micron technology") is what makes "was macht micron gerade?" resolve
    without asking the LLM to guess the symbol.
    """
    lookup: dict[str, str] = {}
    for ticker, name in lexicon.items():
        # Single-letter tickers (V, F, T) are ordinary words in a German sentence — they
        # only ever resolve through their company name.
        if len(ticker) > 1:
            lookup.setdefault(ticker.lower(), ticker)
        parts = _words(short_company_name(name or ""))[:_MAX_NAME_WORDS]
        for span in range(1, len(parts) + 1):
            key = " ".join(parts[:span]).lower()
            if len(key) >= 3:
                lookup.setdefault(key, ticker)
    return lookup


def find_tickers(
    question: str, lexicon: dict[str, str], *, lookup: dict[str, str] | None = None
) -> list[str]:
    """Tickers mentioned in `question`, by symbol or company name, question order,
    deduped. Deterministic on purpose: a wrong retrieval is debuggable, a wrong
    LLM-side guess is not. Callers holding a hot lookup pass it in to skip the rebuild."""
    index = build_lookup(lexicon) if lookup is None else lookup
    words = _words(question)
    hits: list[str] = []
    position = 0
    while position < len(words):
        # Longest match wins: "Alpha Beta Systems" must not resolve to "Alpha".
        for span in range(min(_MAX_NAME_WORDS, len(words) - position), 0, -1):
            key = " ".join(words[position : position + span]).lower()
            ticker = index.get(key)
            if ticker is not None:
                if ticker not in hits:
                    hits.append(ticker)
                position += span
                break
        else:
            position += 1
    return hits
