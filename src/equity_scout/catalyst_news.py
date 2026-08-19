"""Layer 2 of the catalyst radar: classify the market-wide news wire (v16).

Pure decision logic — the runner owns the network and the writes.

## Why this exists next to evidence/event_classifier.py

That classifier answers a different question. It asks "did this earnings release beat or
miss?" for the ~30-70 tickers in `tracked_tickers()`, and it is fed five generic yfinance
headlines per ticker. Measured on the live DB: 816 of 894 classified events came out as
`unknown`, because the input was mostly Zacks valuation commentary rather than wire news.

This module asks the question that was missing: "is this headline the kind of thing that
makes a stock jump?" — for EVERY symbol on the tape, because the wire endpoint carries no
ticker filter. The Moderna case is the proof of need: MRNA was in none of our scope sets, so
no amount of improving the earnings classifier could ever have seen it.

## Why keyword rules and not an LLM

Two reasons, both practical. The sweep runs every minute over the whole tape; an LLM call per
headline is neither affordable nor fast enough on a CPU-only Ollama (measured 60-106 s to
first token on stock questions). And a rule is auditable — when a signal fires, the exact
phrase that triggered it is recorded, which an embedding never gives you. The cost is
recall: a catalyst phrased unusually is missed. That is an accepted, stated limit, and the
ignition scan (layer 1) is the independent net that catches the move regardless of wording.

Strength is a prior, not a measurement: it encodes how large a move this class of news
USUALLY causes, calibrated from nothing but domain knowledge. It ranks candidates against
each other. It must never be read as a probability.
"""
from __future__ import annotations

import re
from datetime import datetime

# (kind, strength, patterns). Order matters: the first match wins, so the sharpest and most
# consequential classes are listed before the generic ones. Patterns are lowercase regex
# fragments matched against the headline; word boundaries are added where a substring would
# misfire.
#
# Branch-neutral by design. Nico's ask was explicit that this must not be a pharma tool, so
# every sector's own jump-makers are represented: approvals and readouts (health care),
# design wins and contract awards (tech/industry), reserve and discovery news (materials),
# charter and rate news (shipping), regulatory decisions (utilities/finance).
_RULES: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    ("merger_acquisition", 0.95, (
        r"\bto (?:be )?acqui(?:re|red)\b", r"\bacquisition of\b", r"\bmerger agreement\b",
        r"\bto merge with\b", r"\btakeover (?:bid|offer)\b", r"\bbuyout offer\b",
        r"\bagrees? to buy\b", r"\bdefinitive agreement to\b", r"\bgo(?:ing)? private\b",
        r"\bstrategic alternatives\b", r"\bunsolicited (?:bid|proposal)\b",
    )),
    ("fda_decision", 0.92, (
        r"\bfda (?:approv|clear|grant|accept|reject)", r"\bapproved by the fda\b",
        r"\bfda approval\b", r"\bcomplete response letter\b", r"\bcrl\b",
        r"\bpdufa\b", r"\bbreakthrough therapy\b", r"\bfast track designation\b",
        r"\bpriority review\b", r"\bema (?:approv|recommend)", r"\bce mark\b",
        r"\bemergency use authorization\b",
    )),
    ("trial_result", 0.90, (
        # "phase 3 results/data" — not a bare "phase 3", which also matches vendor and
        # site-selection announcements (live 2026-08-19: a CRO appointment for a Phase 2/3
        # study was scored as a readout). The result words are what make it a catalyst.
        r"\bphase [123](?:/[123])? (?:trial |study )?(?:results|data|readout|success|failure)\b",
        r"\b(?:results|data) from (?:the )?(?:planned )?(?:phase|interim)",
        r"\bpivotal (?:trial|study)\b", r"\btopline (?:data|results)\b",
        r"\bprimary endpoint\b", r"\bmet its endpoint\b", r"\bmissed (?:its )?endpoint\b",
        r"\bstatistically significant\b", r"\bclinical (?:trial|study) (?:results|data)\b",
        r"\bdata readout\b", r"\binterim analysis\b", r"\btrial (?:success|failure)\b",
    )),
    ("bankruptcy_distress", 0.90, (
        r"\bchapter 11\b", r"\bchapter 7\b", r"\bbankrupt", r"\binsolvenc",
        r"\bdefault(?:s|ed)? on\b", r"\bgoing concern\b", r"\bdelisting\b",
        r"\brestructuring support agreement\b", r"\bmissed (?:a )?(?:debt|interest) payment\b",
    )),
    ("regulatory_legal", 0.75, (
        r"\bantitrust\b", r"\bdoj (?:sues|investigat|approv)", r"\bsec (?:charges|investigat)",
        r"\bftc (?:sues|blocks|approv)", r"\bjury (?:awards|finds)\b", r"\bverdict\b",
        r"\bsettles? (?:for|with)\b.*\$", r"\bpatent (?:win|loss|ruling|invalidat)",
        r"\brecall(?:s|ed)\b", r"\bindicted\b", r"\bsanction",
    )),
    ("guidance_change", 0.72, (
        r"\brais(?:es|ed|ing) (?:its )?(?:full[- ]year |fy\d*\s*)?(?:guidance|outlook|forecast)",
        r"\bcuts? (?:its )?(?:guidance|outlook|forecast)",
        r"\blowers? (?:its )?(?:guidance|outlook|forecast)",
        r"\bwithdraws? (?:its )?(?:guidance|outlook)", r"\bpreannounc",
        r"\bbeats? and rais(?:es|ed)\b", r"\bguidance (?:above|below)\b",
        r"\bprofit warning\b",
    )),
    ("contract_award", 0.70, (
        r"\bawarded (?:a )?(?:\$[\d.]+ ?[bm]|contract)", r"\bwins? (?:a )?\$[\d.]+ ?[bm]",
        r"\b(?:contract|order) worth \$", r"\bdesign win\b", r"\bsupply agreement with\b",
        r"\bpartnership with\b.*\$", r"\bselected by\b.*\bto (?:supply|provide|build)\b",
        r"\bletter of intent\b", r"\bmulti-?year (?:deal|contract|agreement)\b",
    )),
    ("index_event", 0.65, (
        r"\bjoin(?:s|ing)? the s&p 500\b", r"\badded to the (?:s&p|nasdaq|russell)",
        r"\bindex inclusion\b", r"\bremoved from the (?:s&p|nasdaq|russell)",
    )),
    # Before capital_structure on purpose: a REVERSE split is the opposite signal from a
    # split. Seen live on 2026-08-19 ("PMGC Announces 1-For-10 Reverse Stock Split"), where
    # the generic split rule would have scored a listing-rescue manoeuvre as a positive
    # catalyst. Strength sits under MIN_STRENGTH, so it is logged as visible-but-weak
    # rather than fired as a signal.
    ("reverse_split", 0.35, (
        r"\breverse (?:stock )?split\b", r"\b1-for-\d+\b", r"\b1 for \d+ reverse\b",
    )),
    ("capital_structure", 0.60, (
        r"\bstock split\b", r"\bspin[- ]?off\b", r"\bspecial dividend\b",
        r"\b(?:announces|expands) (?:a )?\$[\d.]+ ?[bm].*buyback\b",
        r"\bshare repurchase program\b", r"\btender offer\b",
    )),
    ("dilution", 0.60, (
        r"\bpublic offering\b", r"\bsecondary offering\b", r"\bprices? \$[\d.]+ ?[bm].*offering\b",
        r"\bunderwritten (?:public )?offering\b", r"\bregistered direct offering\b",
        r"\bconvertible (?:notes|debt) offering\b", r"\bat[- ]the[- ]market (?:offering|program)\b",
        r"\bshelf registration\b", r"\bdirect offering\b",
    )),
    # Before earnings_surprise: on the live wire the most common shape of an "earnings"
    # headline is not the release, it is analysts reacting to a release that already
    # happened hours ago ("These Analysts Revise Their Forecasts On Home Depot After Q2").
    # The move is long over by then. Scored as analyst chatter so it stays below the alert
    # threshold instead of buzzing Nico's phone — a noisy radar gets muted, and a muted
    # radar is the same as no radar.
    ("analyst_reaction", 0.30, (
        r"^these analysts\b", r"\banalysts? (?:boost|cut|slash|revise|raise|lower)",
        r"\banalysts? (?:are )?(?:bullish|bearish) on\b",
        r"\bwall street (?:is )?(?:bullish|bearish)\b",
    )),
    ("earnings_surprise", 0.55, (
        r"\bbeats? (?:on )?(?:earnings|eps|revenue|estimates)", r"\bearnings beat\b",
        r"\bmisses? (?:on )?(?:earnings|eps|revenue|estimates)", r"\bearnings miss\b",
        r"\bq[1-4] (?:results|earnings)\b", r"\breports? (?:record|strong|weak) (?:quarter|results)\b",
        r"\bsurges? after (?:earnings|results)\b",
    )),
    ("leadership", 0.45, (
        r"\bceo (?:steps down|resigns|departs|ousted|fired)\b", r"\bnames? new ceo\b",
        r"\bcfo (?:steps down|resigns|departs)\b", r"\bactivist (?:stake|investor|position)\b",
        r"\b13d filing\b", r"\bproxy fight\b",
    )),
    ("operational", 0.45, (
        r"\bdiscover(?:s|y) of\b", r"\bmineral resource estimate\b", r"\breserve (?:upgrade|increase)\b",
        r"\bproduction (?:halt|suspend|record)", r"\bplant (?:fire|explosion|shutdown)\b",
        r"\bcyber(?:attack|security incident)\b", r"\bdata breach\b", r"\bforce majeure\b",
    )),
    ("analyst_action", 0.30, (
        r"\bupgrade[sd]? (?:to|from)\b", r"\bdowngrade[sd]? (?:to|from)\b",
        r"\braises? price target\b", r"\blowers? price target\b",
        r"\binitiate[sd]? (?:coverage|with)\b", r"\bdouble upgrade\b",
    )),
)

_COMPILED = tuple(
    (kind, strength, tuple(re.compile(pattern) for pattern in patterns))
    for kind, strength, patterns in _RULES
)

# German labels for the alert/cockpit text. The code stays English, user-facing text German
# (house rule) — and Nico reads these on his phone, so they have to say what happened.
KIND_LABELS = {
    "merger_acquisition": "Übernahme/Fusion",
    "fda_decision": "Zulassungsentscheidung",
    "trial_result": "Studienergebnis",
    "bankruptcy_distress": "Insolvenz/Notlage",
    "regulatory_legal": "Recht/Regulierung",
    "guidance_change": "Prognose geändert",
    "contract_award": "Großauftrag",
    "index_event": "Index-Änderung",
    "capital_structure": "Kapitalmaßnahme",
    "dilution": "Kapitalerhöhung (verwässernd)",
    "earnings_surprise": "Quartalszahlen",
    "leadership": "Führung/Aktivist",
    "operational": "Betrieb/Produktion",
    "analyst_action": "Analystenurteil",
    "reverse_split": "Reverse Split (Warnsignal)",
    "analyst_reaction": "Analystenreaktion (Bewegung vorbei)",
}

# A wire item tagged with more symbols than this is market commentary ("10 stocks to watch"),
# not a company catalyst. Verified against the live feed: single-company news carries 1-3
# symbols; roundups carry 8+.
MAX_SYMBOLS_PER_ARTICLE = 4

MIN_STRENGTH = 0.40  # below this the wire is noise for our purpose (analyst chatter)


def classify_catalyst(headline: str) -> tuple[str, float, str] | None:
    """(kind, strength, matched_phrase) for the first matching rule, else None.

    The matched phrase is returned and stored so a firing signal can always be audited back
    to the exact words that triggered it — the property an embedding classifier cannot give.
    """
    if not headline:
        return None
    lowered = headline.lower()
    for kind, strength, patterns in _COMPILED:
        for pattern in patterns:
            match = pattern.search(lowered)
            if match:
                return kind, strength, match.group(0)
    return None


def build_news_signals(
    articles: list[dict],
    *,
    now: datetime,
    min_strength: float = MIN_STRENGTH,
    max_symbols: int = MAX_SYMBOLS_PER_ARTICLE,
    known_tickers: set[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """(signals, rejections) from raw wire items — pure, no I/O.

    One signal per (symbol, article): the same headline about an acquisition names both
    parties, and both are catalysts. `known_tickers`, when given, restricts output to symbols
    the broker can actually trade — passing None keeps everything, which is what a pure
    sight-only run wants.
    """
    stamp = now.isoformat(timespec="seconds")
    day_key = now.date().isoformat()
    signals: list[dict] = []
    rejections: list[dict] = []

    for article in articles:
        headline = article.get("headline") or ""
        symbols = [s for s in (article.get("symbols") or []) if s]
        article_id = article.get("id")

        if not symbols:
            continue  # macro/market piece with no company attached — nothing to act on
        if len(symbols) > max_symbols:
            rejections.append({
                "source": "news", "ticker": symbols[0], "reason": "roundup_article",
                "seen_at": day_key,
                "detail": f"{len(symbols)} Symbole — Marktübersicht, kein Einzelfall",
            })
            continue

        classified = classify_catalyst(headline)
        if classified is None:
            continue  # the overwhelming majority: ordinary commentary, silently skipped
        kind, strength, phrase = classified
        if strength < min_strength:
            rejections.append({
                "source": "news", "ticker": symbols[0], "reason": "weak_catalyst",
                "seen_at": day_key,
                "detail": f"{KIND_LABELS.get(kind, kind)} unter Schwelle",
            })
            continue

        for symbol in symbols:
            if known_tickers is not None and symbol not in known_tickers:
                rejections.append({
                    "source": "news", "ticker": symbol, "reason": "not_tradable",
                    "seen_at": day_key, "detail": "nicht in der Handelsliste des Brokers",
                })
                continue
            signals.append({
                "source": "news",
                "ticker": symbol,
                "kind": kind,
                "seen_at": article.get("created_at") or stamp,
                # Keyed on the wire item id, so re-reading an overlapping page writes nothing
                # twice — the sweep deliberately re-reads a margin to survive gaps.
                "dedup_key": f"news:{symbol}:{article_id}",
                "score": strength,
                "detail": f"{KIND_LABELS.get(kind, kind)} — Auslöser: „{phrase}“",
                "headline": headline[:400],
                "url": article.get("url"),
            })

    signals.sort(key=lambda s: s["score"], reverse=True)
    return signals, rejections


def parse_wire(payload: dict) -> tuple[list[dict], str | None]:
    """Alpaca news response -> (articles, next_page_token).

    Kept here rather than in the fetch module because it is pure and testable; the runner
    only owns the HTTP call and the cursor.
    """
    articles = []
    for item in payload.get("news") or []:
        articles.append({
            "id": item.get("id"),
            "headline": item.get("headline") or "",
            "summary": item.get("summary") or "",
            "symbols": item.get("symbols") or [],
            "created_at": item.get("created_at") or item.get("updated_at"),
            "url": item.get("url"),
            "source": item.get("source") or "",
        })
    return articles, payload.get("next_page_token")
