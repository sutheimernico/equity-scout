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


# Single words that must never resolve to a stock on their own, even when exactly one
# company starts with them. Two sources: the curated list voices.py already uses for the
# same problem on headlines, plus German question/finance vocabulary — this assistant is
# asked in German ("Was ist der Kurs von …"), and the lexicon spans ~7 800 titles, so
# ordinary words WILL collide with some company's first word. Multi-word names are never
# blocked: "First Company" stays findable, "First" alone does not.
_GERMAN_STOPWORDS = (
    "was wer wie wann warum wieso wo welche welcher welches der die das den dem des ein "
    "eine einen einem eines und oder aber auch noch nur schon nicht kein keine ist sind "
    "war waren hat haben hatte wird werden wurde kann könnte soll sollte muss müssen mit "
    "von vom für auf aus bei nach über unter vor zwischen seit gegen ohne durch als wenn "
    "dass weil damit sich mein meine meinem deinen unser aktie aktien kurs kurse kaufen "
    "verkauft verkaufen markt märkte depot geld euro dollar jahr jahre monat woche heute "
    "gestern morgen gut gute besser beste schlecht hoch tief mehr weniger viel wenig alle "
    "man ich du wir ihr sie es"
)
# English function words that survive the >=3-char rule and appear as first words in the
# universe ("Are", "Can", "New", "One", "Two", "Big", "Top", "All", "Any", "Now").
_ENGLISH_STOPWORDS = (
    "the and are can new one two big top all any now for you our its his her they этот "
    "has have was were will would could should from with into over under about more less"
)


def _blocked_single_words() -> frozenset[str]:
    from equity_scout.evidence.voices import _GENERIC_FIRST_WORDS

    return frozenset(
        {w.lower() for w in _GENERIC_FIRST_WORDS}
        | set(_GERMAN_STOPWORDS.split())
        | set(_ENGLISH_STOPWORDS.split())
    )


_BLOCKED_SINGLE_WORDS = _blocked_single_words()

# Purely alphabetic symbols only ever match in their own spelling. Length is no defence:
# across 6 197 screened titles German words keep landing on real tickers ("sagt" -> SAGT,
# "mehr" -> MEHR), and a stopword list would need endless upkeep to stay ahead of them.
# Punctuated or digit-bearing symbols ("ITC.NS", "PETR4.SA", "9064.T") cannot be read as
# words, so those stay case-insensitive for phone typing.


def build_lookup(lexicon: dict[str, str]) -> dict[str, str]:
    """key -> ticker. Name keys are lowercased; short symbol keys keep their spelling.

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
            symbol_key = ticker if ticker.isalpha() else ticker.lower()
            lookup.setdefault(symbol_key, ticker)
        # Both spellings are indexed: the full name ("first company") and the one with the
        # legal-form tail removed ("yamato"), so either phrasing in a question resolves.
        full = _words(name or "")[:_MAX_NAME_WORDS]
        short = _words(short_company_name(name or ""))[:_MAX_NAME_WORDS]
        for parts in (full, short):
            for span in range(1, len(parts) + 1):
                key = " ".join(parts[:span]).lower()
                if len(key) < 3:
                    continue
                if span == 1 and key in _BLOCKED_SINGLE_WORDS:
                    continue
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
            key = " ".join(words[position : position + span])
            # Exact spelling first (that is how short symbols like "ON" are indexed),
            # then the lowercased key for names and unambiguous symbols.
            ticker = index.get(key) or index.get(key.lower())
            if ticker is not None:
                if ticker not in hits:
                    hits.append(ticker)
                position += span
                break
        else:
            position += 1
    return hits


_STATUS_DE = {"open": "offen", "buy": "Gekauft", "pass": "Abgelehnt",
              "later": "Später", "expired": "Verfallen"}


def _de(value: float, digits: int = 1) -> str:
    """German decimal comma — the assistant answers in German, so its numbers do too."""
    return f"{value:.{digits}f}".replace(".", ",")


def _pct(value: float, *, signed: bool = False, digits: int = 1) -> str:
    text = _de(value * 100, digits)
    return f"+{text}" if signed and value > 0 else text


def stock_dossier(
    *,
    ticker: str,
    name: str | None,
    watchlist_entry: dict | None,
    fundamentals,  # Fundamentals | None
    insight: dict | None,
    pitches: list[dict],
    evidence_events: list[dict],
    held_by: dict[str, float],
    metrics: dict | None = None,
    metrics_fetched_on: str | None = None,
    factor_breakdown: dict | None = None,
    fscore: dict | None = None,
    next_earnings: str | None = None,
) -> str:
    """Everything the app knows about one ticker, as prompt lines. Absences are SAID
    ("nicht auf der aktuellen Watchlist") — the measurement showed the model inventing
    reasons exactly where the context was silent."""
    lines = [f"AKTIE {name or ticker} ({ticker}):"]
    if fundamentals is not None and (fundamentals.sector or fundamentals.industry):
        branch = " / ".join(x for x in (fundamentals.sector, fundamentals.industry) if x)
        currency = f", Handelswährung {fundamentals.currency}" if fundamentals.currency else ""
        lines.append(f"- Branche: {branch}{currency}")
    if metrics:
        lines.extend(metrics_lines(metrics, fetched_on=metrics_fetched_on or "unbekannt"))
    if factor_breakdown:
        ranked = " · ".join(
            f"{_FACTOR_LABELS.get(family, family)} {round(value * 100)}/100"
            for family, value in factor_breakdown.items()
            if value is not None
        )
        # Percentiles, not absolutes: 87/100 means "cheaper than 87 % of its sector peers".
        lines.append(f"- Faktor-Perzentile im Vergleich (0-100): {ranked}")
    if fscore is not None and fscore.get("score") is not None:
        lines.append(
            f"- Bilanz-Trend (F-Score) {fscore['score']} von {fscore.get('evaluable', 9)} "
            f"Kriterien erfüllt (Geschäftsjahr {fscore.get('fiscal_year', '?')})."
        )
    if watchlist_entry is not None:
        score = round(watchlist_entry["composite"] * 100)
        lines.append(
            f"- Watchlist: Einstiegs-Score {score}/100, Kurs {watchlist_entry['price']}, "
            f"Zone {watchlist_entry['entry_zone_low']}–{watchlist_entry['entry_zone_high']} "
            f"({watchlist_entry['zone_note']})"
        )
    else:
        lines.append("- Steht NICHT auf der aktuellen Watchlist (wird gerade nicht beobachtet).")
    if fundamentals is not None and fundamentals.analyst_target is not None:
        lines.append(
            f"- Analysten-Konsens: Ø-Kursziel {fundamentals.analyst_target} "
            f"({fundamentals.analyst_count or '?'} Schätzungen) — Meinung Dritter."
        )
    else:
        lines.append("- Keine Analysten-Daten im Cache.")
    if fundamentals is not None and fundamentals.year_high is not None:
        # The honest reference for names no analyst covers: geometry, not a target.
        lines.append(f"- 52-Wochen-Hoch {fundamentals.year_high} (Kursmarke, kein Kursziel).")
    if next_earnings:
        lines.append(f"- Nächster Termin: Quartalszahlen am {next_earnings}.")
    if insight is not None:
        if insight.get("business"):
            lines.append(f"- Profil: {insight['business']}")
        if insight.get("news_summary"):
            lines.append(f"- News-Zusammenfassung: {insight['news_summary']}")
    for p in pitches[:3]:
        status = _STATUS_DE.get(p["status"], p["status"])
        lines.append(
            f"- Pitch vom {p['created_at'][:10]}: Score {round(p['composite'] * 100)}/100, "
            f"Status {status}."
        )
    for e in evidence_events[:3]:
        lines.append(f"- Externes Signal ({e['source']}, {e['event_date']}).")
    for lane, shares in held_by.items():
        if shares > 0:
            label = "Dein Depot" if lane == "nico" else "Autopilot-Depot"
            lines.append(f"- {label} hält {shares} Anteile.")
    return "\n".join(lines)


# metric key -> (German label, renderer). One place for the vocabulary the assistant is
# asked in: "KGV", "Kennzahlen", "Marge" must land on the same numbers the screener ranks.
_METRIC_LABELS: dict[str, str] = {
    "trailing_pe": "KGV",
    "price_to_book": "Kurs-Buchwert-Verhältnis",
    "return_on_equity": "Eigenkapitalrendite",
    "profit_margins": "Nettomarge",
    "revenue_growth": "Umsatzwachstum",
    "earnings_growth": "Gewinnwachstum",
    "momentum_6m": "6-Monats-Rendite",
    "volatility_6m": "Tagesschwankung",
    "high_52w_proximity": "Nähe zum 52-Wochen-Hoch",
    "price": "Kurs",
}
# Metrics stored as a ratio (0.17 = 17 %); the rest are plain numbers.
_PERCENT_METRICS = frozenset({
    "return_on_equity", "profit_margins", "revenue_growth", "earnings_growth",
    "momentum_6m", "volatility_6m",
})
_SIGNED_METRICS = frozenset({"revenue_growth", "earnings_growth", "momentum_6m"})


def _metric_text(key: str, value: float) -> str:
    label = _METRIC_LABELS[key]
    if key == "high_52w_proximity":
        return f"Kurs steht bei {_de(value * 100, 0)} % seines 52-Wochen-Hochs"
    if key in _PERCENT_METRICS:
        return f"{label} {_pct(value, signed=key in _SIGNED_METRICS)} %"
    if key == "trailing_pe" and value < 0:
        # A negative P/E is not "cheap" — it means the company loses money. factors.py drops
        # it from the value ranking for exactly that reason; the assistant must say it.
        return f"KGV {_de(value)} (negativ — das Unternehmen schreibt derzeit Verlust)"
    return f"{label} {_de(value)}"


def metrics_lines(metrics: dict, *, fetched_on: str) -> list[str]:
    """The cached key figures of one ticker as prompt lines, German units and decimal comma.

    Source is the screener's own quote cache (7 778 titles as of 2026-08-07), so a KGV
    question is answered from the same number the ranking used — not from the model's
    training data. Missing values are listed by name: silence is what made the measured
    assistant invent them.
    """
    present = [
        _metric_text(key, float(metrics[key]))
        for key in _METRIC_LABELS
        if metrics.get(key) is not None
    ]
    missing = [_METRIC_LABELS[key] for key in _METRIC_LABELS if metrics.get(key) is None]
    lines: list[str] = []
    if present:
        lines.append(f"- Kennzahlen (Stand {fetched_on}): " + " · ".join(present))
    if missing:
        lines.append(f"- Ohne Wert im Cache: {', '.join(missing)}")
    return lines


# Factor family -> the plain-German name the dashboard uses for it.
_FACTOR_LABELS = {
    "value": "Substanz-Bewertung", "quality": "Qualität", "momentum": "Trendstärke",
    "growth": "Wachstum", "low_vol": "Ruhe im Kurs",
}


# Capitalised words that look like tickers but are vocabulary. Without this, "Was sagt das
# KGV?" would spend the question's one live lookup on a metric name.
_NOT_A_SYMBOL = frozenset(
    "KGV KBV KUV KCV ETF ETFS REIT IPO EPS ROE ROI ROA EBIT EBITDA CAGR DSR PBO "
    "USD EUR CHF GBP JPY CAD AUD CNY INR BRL SEK NOK DKK "
    "EU US USA UK DE JP CN IN BR CH AT NL FR IT ES "
    "DAX MDAX SDAX TECDAX NASDAQ NYSE SEC EZB FED BIP KI AI ML LLM API URL FAQ PDF "
    "CEO CFO CTO COO WKN ISIN AG SE KG GMBH NV SA PLC INC LTD ADR ADS "
    "OK ZB BZW USW GGF INKL EXKL MWST".split()
)
# Ticker shape: 2-5 letters, optionally an exchange suffix (RHM.DE, ITC.NS, BRK-B).
_SYMBOL_SHAPE_RE = re.compile(r"[A-Z]{2,5}(?:[.\-][A-Z0-9]{1,3})?$")


def candidate_symbols(question: str, *, known: set[str] | None = None) -> list[str]:
    """Ticker-shaped words the lexicon does NOT know, question order, deduped.

    These are the only symbols worth a live lookup: everything the screener ever saw is
    already in the lexicon, so a leftover is either a foreign listing (RHM.DE) or a typo.
    Callers spend at most one lookup per question — see api.py.
    """
    seen = {t.upper() for t in (known or set())}
    out: list[str] = []
    for word in _words(question):
        if word.upper() in _NOT_A_SYMBOL or word.upper() in seen:
            continue
        # Uppercase spelling required, same reason as build_lookup: lowercase is language.
        if word == word.upper() and _SYMBOL_SHAPE_RE.fullmatch(word) and word not in out:
            out.append(word)
    return out


_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "depots": ("depot", "portfolio", "position", "autotrader", "auto-depot", "lane",
               "gekauft", "verkauft", "hält", "bestand", "anteile"),
    "ergebnisse": ("ergebnis", "bilanz", "sharpe", "drawdown", "track record",
                   "funktioniert", "benchmark", "rendite", "performance", "gewinn"),
    "personen": ("buffett", "burry", "ackman", "kongress", "insider", "politiker",
                 "wer hat", "investor", "mitglied", "senator", "abgeordnet", "fonds",
                 "13f", "form 4", "gekauft hat", "stimmen"),
    "markt": ("marktlage", "risk-on", "risk on", "regime", "vix", "markt", "sektor"),
    "strategien": ("strategie", "60/40", "momentum", "ml", "signal-filter",
                   "research", "pbo", "champion", "modell"),
    "inbox": ("pitch", "inbox", "entscheidung", "offen", "verfallen"),
    # Key figures get their own topic: those questions need the metric glossary, and
    # nothing else — folding the whole dashboard in would only distract a 7B model.
    "kennzahlen": ("kgv", "kurs-gewinn", "kennzahl", "marge", "bewertung", "buchwert",
                   "eigenkapital", "wachstum", "verschuld", "dividende", "umsatz",
                   "gewinnwachstum", "volatil", "schwankung", "f-score", "bilanztrend"),
}


def route_topics(question: str) -> list[str]:
    """Which base context blocks the question needs. Deterministic keyword routing —
    a 7B model gets calmer, better answers from a short, relevant prompt than from
    everything at once. No match -> the compact overview block."""
    q = question.lower()
    topics = [t for t, words in _TOPIC_KEYWORDS.items() if any(w in q for w in words)]
    return topics or ["ueberblick"]


# The feed mixes congress with executive-branch filers (the 2026-08-07 backfill pulled the
# full OGE index, e.g. "oge_donald_trump"), so "Kongress" alone would mislabel some rows.
_CHAMBER_DE = {"senate": "Senat", "house": "Repräsentantenhaus",
               "executive": "Regierung/Exekutive"}
_PARTY_DE = {"R": "Republikaner", "D": "Demokraten", "I": "unabhängig"}
_UNKNOWN_PARTY = "Partei unbekannt"
_UNKNOWN_CHAMBER = "Amt unbekannt"
_FUND_CHANGE_DE = {"new": "neue Position", "increased": "aufgestockt",
                   "reduced": "reduziert", "closed": "verkauft"}
_VOICE_KIND_DE = {"buy": "Kauf-Aussage", "sell": "Verkaufs-Aussage",
                  "context": "Erwähnung"}
# The 8-K item codes that actually occur in the feed, in plain German. Anything else is
# rendered as its bare code rather than guessed at.
_EIGHTK_ITEMS_DE = {
    "1.01": "wesentliche Vereinbarung", "2.02": "Quartalszahlen",
    "2.01": "Übernahme oder Verkauf", "5.02": "Wechsel in Vorstand/Aufsichtsrat",
    "7.01": "Mitteilung an den Kapitalmarkt", "8.01": "sonstiges Ereignis",
}


def _congress_line(event: dict) -> str:
    d = event["details"]
    who = d.get("politician") or "unbekannt"
    party = _PARTY_DE.get(str(d.get("party") or ""), d.get("party") or _UNKNOWN_PARTY)
    chamber = _CHAMBER_DE.get(str(d.get("chamber") or ""), d.get("chamber") or _UNKNOWN_CHAMBER)
    bought = d.get("transaction_date") or event["event_date"]
    filed = d.get("filing_date") or event["event_date"]
    amount = d.get("amount_range") or "Volumen unbekannt"
    lag = d.get("days_to_file")
    # The lag is the story: a filing can be years older than it looks, and treating it as
    # fresh news is the single easiest way to misread this feed.
    lag_text = f", {lag} Tage Meldeverzug" if lag is not None else ""
    return (
        f"- Gemeldeter Kauf: {who} ({party}, {chamber}) — gekauft am {bought}, "
        f"gemeldet {filed}{lag_text}, Volumen {amount}."
    )


def _fund_line(event: dict) -> str:
    d = event["details"]
    change = _FUND_CHANGE_DE.get(str(d.get("change") or ""), d.get("change") or "?")
    shares = d.get("shares")
    shares_text = f", {_de(float(shares), 0)} Anteile" if shares else ""
    return (
        f"- Fonds-Meldung (13F): {d.get('fund', 'Fonds')} — {change} "
        f"(Quartalsende {d.get('period', '?')}, gemeldet {d.get('filed_at', '?')})"
        f"{shares_text}."
    )


def _voice_line(event: dict) -> str:
    d = event["details"]
    kind = _VOICE_KIND_DE.get(str(d.get("kind") or ""), d.get("kind") or "Erwähnung")
    return (
        f"- Stimme: {d.get('speaker', 'unbekannt')} — {kind} am {event['event_date']} "
        f"(\"{d.get('headline', '')}\"). Presse-Erwähnung, keine Meldung."
    )


def _eightk_line(event: dict) -> str:
    items = event["details"].get("items") or []
    named = ", ".join(_EIGHTK_ITEMS_DE.get(str(i), f"Punkt {i}") for i in items) or "ohne Angabe"
    return f"- Pflichtmitteilung (8-K) am {event['event_date']}: {named}."


def _theme_line(event: dict) -> str:
    d = event["details"]
    return (
        f"- Nachrichten-Thema \"{d.get('theme', '?')}\" am {event['event_date']} "
        f"({d.get('hits', '?')} Treffer)."
    )


_EVENT_RENDERERS = {
    "congress": _congress_line, "thirteen_f": _fund_line, "voice": _voice_line,
    "edgar_8k": _eightk_line, "news_theme": _theme_line,
}


def people_lines(events: list[dict]) -> list[str]:
    """Who bought, who sold, who talked — one line per event, names spelled out.

    Answers both "wer hat X gekauft" and "was hat Person Y gekauft" from the same rows.
    An empty list gets an explicit sentence: the measured assistant filled silence with
    invented buyers.
    """
    if not events:
        return ["- Keine gemeldeten Käufe oder Stimmen zu diesem Titel."]
    lines: list[str] = []
    for event in events:
        render = _EVENT_RENDERERS.get(event.get("source", ""))
        if render is not None:
            lines.append(render(event))
    return lines or ["- Keine gemeldeten Käufe oder Stimmen zu diesem Titel."]


def find_persons(question: str, names: list[str]) -> list[str]:
    """Tracked people mentioned in the question, by full name or unambiguous surname.

    Ambiguous surnames resolve to nothing on purpose — attributing a trade to the wrong
    person is worse than admitting the question was unclear.
    """
    index: dict[str, str] = {}
    surname_owners: dict[str, set[str]] = {}
    for name in names:
        index.setdefault(name.lower(), name)
        parts = _words(name)
        if parts:
            surname_owners.setdefault(parts[-1].lower(), set()).add(name)
    for surname, owners in surname_owners.items():
        if len(owners) == 1 and len(surname) >= 4:
            index.setdefault(surname, next(iter(owners)))
    words = _words(question)
    hits: list[str] = []
    position = 0
    while position < len(words):
        for span in range(min(4, len(words) - position), 0, -1):
            key = " ".join(words[position : position + span]).lower()
            person = index.get(key)
            if person is not None:
                if person not in hits:
                    hits.append(person)
                position += span
                break
        else:
            position += 1
    return hits
