"""Aus einem Kaufplan wird eine Meldung, die ein Laie versteht (2026-08-27).

Nicos Auftrag: „ich will frühzeitig bei Möglichkeiten und Chancen benachrichtigt werden,
mit Zusammenfassungen von KI, warum ich jetzt das kaufen sollte, warum es sich lohnt,
sehr übersichtlich und einfach und verständlich für Laien."

Der Kaufplan (`buy_plan.py`) hat die Zahlen. Was fehlte, ist die Übersetzung: „Score 72,
Stance kaufbereit, gap_pct 0.0" ist für jemanden, der keine Märkte verfolgt, keine
Information. Dieses Modul macht daraus vier Sätze — Anlass, Begründung, Gegenrede, Plan.

Drei Regeln, die diese Übersetzung ehrlich halten:

- **Das Sprachmodell wählt nicht aus und rechnet nicht.** Auswahl und Rangfolge macht
  `select_opportunities` aus gemessenen Feldern; das LLM formuliert nur, was schon
  dasteht. (LOOP.md: „do not let the LLM predict or rank" — eine Chance, die ein Modell
  erfunden hat, wäre genau die Art Vorschlag, die niemand nachprüfen kann.)
- **Ohne LLM gibt es trotzdem eine Meldung.** Ollama läuft auf Nicos CPU und ist oft aus.
  Der Regel-Text ist deshalb nicht der Notfall, sondern der Normalfall — das LLM setzt
  obendrauf. `explained_by` sagt an jeder Meldung, welcher der beiden es war.
- **Jede Meldung trägt ihre Gegenrede.** Eine Benachrichtigung, die nur Gründe dafür
  nennt, ist Werbung. `risk_line` ist Pflichtfeld, nicht Option.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

# Ab diesem Score gilt ein Titel als meldenswert. Deckungsgleich mit notify.DEFAULT_THRESHOLD
# (0.45 auf der 0-1-Skala) — dieselbe Qualitätsschwelle, die seit v8 „kein Müll" durchsetzt,
# hier auf der 0-100-Skala der Kaufpläne.
MIN_SCORE = 45
# Wie oft derselbe Titel gemeldet werden darf. Eine Kaufzone verschwindet nicht über Nacht;
# täglich dieselbe Aktie zu melden trainiert nur an, Meldungen wegzuwischen.
COOLDOWN_DAYS = 7
# Wie viele Chancen eine Meldung höchstens trägt. Mehr als drei liest niemand am Handy, und
# „die besten drei" ist eine ehrlichere Aussage als eine Liste, die Rang 9 mitnimmt.
MAX_PER_RUN = 3

# Nur diese Haltung ist eine Chance, auf die man heute reagieren kann.
ACTIONABLE_STANCES = ("kaufbereit",)

# „Frühzeitig" (Nicos Wort) heißt: melden, BEVOR der Kurs in der Zone steht. Ein Titel
# knapp darüber ist keine Kaufgelegenheit — aber eine Limit-Gelegenheit: die Order liegt
# im Depot und greift von selbst, wenn der Kurs kommt. Ohne diese zweite Klasse hätte das
# System am 2026-08-27 exakt null Meldungen gehabt (1 kaufbereiter Titel in 30, und der
# war über ein deutsches Depot nicht handelbar).
APPROACHING_STANCES = ("warten",)
# Wie weit über der Zone „bald" noch bald ist. Deckungsgleich mit buy_plan.NEAR_ZONE_LIMIT_PCT
# und aktien.ts' NEAR_LIMIT — dieselbe Grenze darf nicht dreimal getippt werden.
APPROACHING_MAX_GAP_PCT = 5.0

KIND_READY = "chance"
KIND_APPROACHING = "bald"

# Handelbarkeit ist ein Auswahlkriterium, keine Fußnote. Ein Titel an der indischen Börse
# kann noch so gut bewertet sein — wenn Nicos Depot ihn nicht kauft, ist die Meldung keine
# Chance, sondern eine Enttäuschung mit Extraschritten. (Befund vom 2026-08-27: der erste
# Trockenlauf meldete ITC.NS als einzigen Kandidaten.)
TRADABLE_LEVELS = ("heimisch", "europäische Börse", "US-Börse")

# Die Faktornamen des Screens in Alltagssprache. Der Screen misst Perzentile innerhalb des
# Universums — „100/100" heißt „unter den besten des Universums", NICHT „perfekt". Die
# Formulierungen müssen diesen Unterschied tragen, sonst liest sich jede Meldung wie ein
# Gütesiegel.
FACTOR_SENTENCES = {
    "value": "Gemessen an Gewinn und Buchwert ist die Aktie {band} bewertet als der Rest des Feldes.",
    "quality": "Das Unternehmen verdient {band} zuverlässig Geld als der Durchschnitt — "
               "stabile Margen, keine überdehnte Bilanz.",
    "momentum": "Der Kurs läuft seit Monaten {band} als der Markt.",
    "growth": "Umsatz und Gewinn wachsen {band} als beim Rest des Feldes.",
    "low_vol": "Der Kurs schwankt {band} als der Markt — ruhigere Position.",
    "size": "Gemessen an der Größe sitzt der Titel {band} im Feld.",
}


def _band_words(score: int) -> str:
    """Perzentil -> Vergleichswort. Nie „sehr gut" — die Zahl ist ein Rang, kein Urteil."""
    if score >= 90:
        return "deutlich besser"
    if score >= 70:
        return "spürbar besser"
    return "etwas besser"


def factor_sentence(factor: dict) -> str | None:
    """{"name": "value", "score": 100} -> ein Satz, den ein Laie versteht."""
    name = str(factor.get("name") or "").lower()
    score = int(factor.get("score") or 0)
    template = FACTOR_SENTENCES.get(name)
    if template is None or score <= 0:
        return None
    if name == "value":
        band = {True: "deutlich günstiger", False: "günstiger"}[score >= 70]
        return template.format(band=band)
    return template.format(band=_band_words(score))


@dataclass(frozen=True)
class Opportunity:
    """Eine Chance in der Sprache, in der man sie jemandem am Telefon erklären würde."""

    kind: str              # "chance" (heute handelbar) | "bald" (Limit legen)
    ticker: str
    name: str
    headline: str          # eine Zeile: was ist der Anlass
    one_liner: str         # die Zeile für den Sperrbildschirm
    why_now: list[str]     # warum ausgerechnet jetzt — je ein ganzer Satz
    risk: str              # was dagegen spricht
    plan_line: str         # was man konkret tun würde
    verdict: str           # das Fazit in Alltagssprache
    score: int | None
    stance: str
    price: float
    currency: str | None
    limit: float | None
    horizon: str
    track_record: str | None
    explained_by: str = "regeln"   # "llm" sobald ein Modell den Text formuliert hat
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _money(value: float | None, currency: str | None) -> str:
    if value is None:
        return "—"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "CHF": "CHF", "JPY": "¥"}.get(
        (currency or "").upper(), currency or ""
    )
    rendered = f"{value:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return f"{rendered} {symbol}".strip()


def score_words(score: int | None) -> str:
    """Die 0-100-Zahl in Worten. Ein Score ist ein RANG im Screening, keine Note für das
    Unternehmen — die Formulierung muss das tragen, sonst liest sich 72 wie eine 2+."""
    if score is None:
        return "ohne Bewertung"
    if score >= 70:
        return "einer der am besten bewerteten Titel im Screening"
    if score >= 55:
        return "im oberen Drittel des Screenings"
    if score >= MIN_SCORE:
        return "über der Qualitätsschwelle, aber kein Spitzenwert"
    return "unter der Qualitätsschwelle"


def buyer_sentence(buyers: list[dict]) -> str | None:
    """„Wer hat sonst noch gekauft" — der Satz, der Laien am meisten sagt, sofern es ihn gibt."""
    if not buyers:
        return None
    kinds = {b.get("kind") or b.get("label") for b in buyers}
    labels = {
        "politician": "Kongressmitglieder",
        "insider": "Manager des Unternehmens selbst",
        "fund": "große Fonds",
    }
    named = [labels.get(str(k), None) for k in kinds]
    named = [n for n in named if n]
    if not named:
        return None
    who = named[0] if len(named) == 1 else " und ".join([", ".join(named[:-1]), named[-1]])
    return f"Gemeldete Käufe der letzten Wochen kommen von {who} ({len(buyers)} Meldungen)."


def why_now_lines(plan: dict) -> list[str]:
    """Drei bis vier ganze Sätze, aus gemessenen Feldern — nie aus einer Schätzung."""
    lines: list[str] = []
    entry = plan.get("entry") or {}
    exit_ = plan.get("exit") or {}
    price = plan.get("price") or 0.0
    currency = plan.get("currency")

    stance_note = entry.get("stance_note")
    if stance_note:
        lines.append(str(stance_note))

    score = plan.get("score")
    if score is not None:
        lines.append(
            f"Im Screening über rund 1 200 Titel ist er {score_words(int(score))} "
            f"(Punktzahl {int(score)} von 100)."
        )

    # Reihenfolge nach Aussagekraft für einen Laien, NICHT nach Herkunft im Code. Wer
    # sonst gekauft hat, ist die konkreteste Information auf der ganzen Karte — sie stand
    # ursprünglich hinter den Faktoren und fiel deshalb der Deckelung auf vier Zeilen zum
    # Opfer (gefunden im Test, 2026-08-27).
    buyers = buyer_sentence(plan.get("buyers") or [])
    if buyers:
        lines.append(buyers)

    # Die Faktoren als Sätze, nicht als „value: 100/100" — genau die Zeile, an der der
    # erste Trockenlauf als „nicht für Laien" durchgefallen ist.
    for factor in (plan.get("factors") or [])[:2]:
        sentence = factor_sentence(factor)
        if sentence and sentence not in lines:
            lines.append(sentence)

    target = exit_.get("analyst_target")
    count = exit_.get("analyst_count")
    if target and price > 0 and count:
        upside = round((target / price - 1.0) * 100)
        # Analystenziele sind fremde Meinungen, keine Messung von uns. Der Satz muss das
        # sagen, sonst liest er sich wie eine Prognose des Scouts.
        lines.append(
            f"{count} Analysten sehen den Wert im Schnitt bei {_money(target, currency)} — "
            f"das wären {upside:+d} % gegenüber heute. Fremde Meinung, keine Messung."
        )
    return lines[:4]


def risk_line(plan: dict) -> str:
    """Die Gegenrede. Immer vorhanden — im Zweifel die strukturelle."""
    entry = plan.get("entry") or {}
    exit_ = plan.get("exit") or {}
    reasons: list[str] = []

    stop = exit_.get("stop")
    price = plan.get("price") or 0.0
    if stop and price > 0:
        loss = round((stop / price - 1.0) * 100)
        reasons.append(
            f"Fällt der Kurs unter {_money(stop, plan.get('currency'))} ({loss:+d} %), "
            f"ist die Idee widerlegt — dann verkaufen, nicht nachkaufen."
        )
    tradability = plan.get("tradability") or {}
    if tradability.get("note"):
        reasons.append(str(tradability["note"]))
    if not entry.get("limit"):
        reasons.append("Es gibt keinen sauberen Halt, an dem sich ein Limit orientieren ließe.")

    reasons.append(
        "Und die grundsätzliche: Screening-Verfahren wie dieses schlagen den Markt nicht "
        "zuverlässig. Setze nur, was du liegen lassen kannst."
    )
    return " ".join(reasons[:3])


def plan_line(plan: dict) -> str:
    """Was man konkret täte — als Satz, nicht als Tabelle.

    Bei „bald" ist die Handlung ausdrücklich eine LIMIT-ORDER, kein Kauf: der Kurs steht
    noch über der Zone, und „kauf jetzt" wäre genau die Ungeduld, gegen die die Zone da ist.
    """
    entry = plan.get("entry") or {}
    currency = plan.get("currency")
    limit = entry.get("limit")
    tranches = entry.get("tranches") or []
    approaching = plan.get("notification_kind") == KIND_APPROACHING
    parts: list[str] = []
    if limit and approaching:
        parts.append(
            f"Noch nichts tun — Kauflimit {_money(limit, currency)} ins Depot legen, "
            "dann greift die Order von selbst"
        )
    elif limit:
        parts.append(f"Kauflimit {_money(limit, currency)}")
    else:
        parts.append(f"Kurs aktuell {_money(plan.get('price'), currency)}")
    if len(tranches) > 1:
        parts.append(f"in {len(tranches)} Schritten statt auf einmal")
    sizing = plan.get("sizing") or {}
    if sizing.get("max_share_pct"):
        parts.append(f"höchstens {sizing['max_share_pct']:.0f} % deines Depots")
    exit_ = plan.get("exit") or {}
    if exit_.get("target"):
        parts.append(f"Ziel {_money(exit_['target'], currency)}")
    if exit_.get("stop"):
        parts.append(f"Ausstieg unter {_money(exit_['stop'], currency)}")
    return ", ".join(parts) + "."


def headline(plan: dict) -> str:
    name = plan.get("name") or plan.get("ticker")
    entry = plan.get("entry") or {}
    stance = entry.get("stance") or ""
    if stance == "kaufbereit":
        return f"{name} steht in seiner Kaufzone"
    if stance == "warten":
        gap = entry.get("gap_pct")
        if gap is not None:
            return f"{name} ist noch {gap:.0f} % von der Kaufzone entfernt"
        return f"{name} nähert sich seiner Kaufzone"
    return f"{name}: {stance}" if stance else str(name)


def one_liner(plan: dict) -> str:
    """Die Zeile auf dem Sperrbildschirm: Kurs, Limit, ein Grund. Nichts sonst — was hier
    nicht in zwei Zeilen passt, liest niemand."""
    entry = plan.get("entry") or {}
    currency = plan.get("currency")
    bits = [f"Kurs {_money(plan.get('price'), currency)}"]
    if entry.get("limit"):
        bits.append(f"Limit {_money(entry['limit'], currency)}")
    score = plan.get("score")
    if score is not None:
        bits.append(f"Score {int(score)}/100")
    reason = next((str(r) for r in (plan.get("why") or []) if r), None)
    tail = f" · {reason}" if reason else ""
    return " · ".join(bits) + tail


def verdict_line(plan: dict) -> str:
    """Das Fazit, das ein Laie als Erstes liest — bewusst ohne Empfehlungswortlaut."""
    if plan.get("notification_kind") == KIND_APPROACHING:
        gap = (plan.get("entry") or {}).get("gap_pct")
        distance = f"{gap:.0f} %" if gap is not None else "wenige Prozent"
        return (
            f"Noch {distance} zu teuer für den eigenen Plan. Das ist keine Kaufmeldung, "
            "sondern der Hinweis, jetzt das Limit zu legen."
        )
    score = plan.get("score")
    buyers = plan.get("buyers") or []
    if score is not None and int(score) >= 70 and buyers:
        return ("Starke Kennzahlen, günstiger Kurs, und andere kaufen ebenfalls — von allen "
                "heutigen Kandidaten der am besten belegte.")
    if score is not None and int(score) >= 70:
        return "Starke Kennzahlen bei einem Kurs, der gerade auf seiner Unterstützung steht."
    if buyers:
        return "Solide Kennzahlen — und es gibt gemeldete Käufe von Leuten mit Einblick."
    return "Ordentliche Kennzahlen, Kurs am unteren Rand der Spanne. Kein Ausrufezeichen."


def select_opportunities(
    plans: list[dict],
    *,
    last_notified: Callable[[str], str | None] | None = None,
    today: str,
    min_score: int = MIN_SCORE,
    cooldown_days: int = COOLDOWN_DAYS,
    max_count: int = MAX_PER_RUN,
    require_tradable: bool = True,
    include_approaching: bool = True,
) -> list[dict]:
    """Welche Kaufpläne heute eine Meldung wert sind. Reine Auswahl über gemessene Felder.

    Reihenfolge: Score absteigend. Kein Zufall, kein Modell — die Rangfolge muss
    nachvollziehbar sein, wenn Nico in drei Wochen fragt, warum ausgerechnet dieser Titel
    kam.
    """
    from datetime import date

    def _fresh_enough(ticker: str) -> bool:
        if last_notified is None:
            return True
        previous = last_notified(ticker)
        if not previous:
            return True
        try:
            delta = date.fromisoformat(today[:10]) - date.fromisoformat(previous[:10])
        except ValueError:
            return True
        return delta.days >= cooldown_days

    def _tradable(plan: dict) -> bool:
        if not require_tradable:
            return True
        return ((plan.get("tradability") or {}).get("level")) in TRADABLE_LEVELS

    def _eligible(plan: dict) -> bool:
        return (
            plan.get("score") is not None
            and int(plan["score"]) >= min_score
            and _tradable(plan)
            and _fresh_enough(str(plan.get("ticker")))
        )

    def _approaching(plan: dict) -> bool:
        entry = plan.get("entry") or {}
        if entry.get("stance") not in APPROACHING_STANCES:
            return False
        gap = entry.get("gap_pct")
        return gap is not None and 0 <= gap <= APPROACHING_MAX_GAP_PCT

    ready = [
        plan for plan in plans
        if (plan.get("entry") or {}).get("stance") in ACTIONABLE_STANCES and _eligible(plan)
    ]
    ready.sort(key=lambda p: int(p["score"]), reverse=True)
    if not include_approaching:
        return [dict(plan, notification_kind=KIND_READY) for plan in ready[:max_count]]

    soon = [plan for plan in plans if _approaching(plan) and _eligible(plan)]
    # Innerhalb der zweiten Klasse zählt die NÄHE zur Zone, nicht der Score: ein Titel, der
    # morgen greifen kann, ist eine frühere Meldung wert als einer, der 4,9 % entfernt ist.
    soon.sort(key=lambda p: ((p.get("entry") or {}).get("gap_pct") or 0.0))

    # Kaufbereite Titel kommen immer zuerst — sie sind die Meldung, auf die man heute
    # reagieren kann. „Bald" füllt nur den Rest des Kontingents auf.
    chosen = [dict(plan, notification_kind=KIND_READY) for plan in ready[:max_count]]
    remaining = max_count - len(chosen)
    if remaining > 0:
        chosen += [dict(plan, notification_kind=KIND_APPROACHING) for plan in soon[:remaining]]
    return chosen


def build_opportunity(plan: dict) -> Opportunity:
    """Kaufplan -> Meldung, rein regelbasiert. Der LLM-Schliff kommt danach, optional."""
    entry = plan.get("entry") or {}
    track = plan.get("track_record") or {}
    return Opportunity(
        kind=str(plan.get("notification_kind") or KIND_READY),
        ticker=str(plan.get("ticker")),
        name=str(plan.get("name") or plan.get("ticker")),
        headline=headline(plan),
        one_liner=one_liner(plan),
        why_now=why_now_lines(plan),
        risk=risk_line(plan),
        plan_line=plan_line(plan),
        verdict=verdict_line(plan),
        score=int(plan["score"]) if plan.get("score") is not None else None,
        stance=str(entry.get("stance") or ""),
        price=float(plan.get("price") or 0.0),
        currency=plan.get("currency"),
        limit=entry.get("limit"),
        horizon=str(plan.get("horizon") or "lang"),
        track_record=track.get("line") if isinstance(track, dict) else None,
        sources=[str(b.get("kind") or "") for b in (plan.get("buyers") or [])],
    )


# --- LLM-Schliff -----------------------------------------------------------------------
# Das Modell bekommt AUSSCHLIESSLICH die Sätze, die oben schon aus Messwerten gebaut wurden,
# und die Aufgabe, sie umzuformulieren. Es bekommt bewusst keine Rohzahlen, aus denen es
# etwas Neues ableiten könnte, und keine Frage, die eine Prognose provoziert.
LLM_SYSTEM = (
    "Du formulierst Finanz-Informationen für einen Laien um. Du erfindest NICHTS: keine "
    "Zahlen, keine Kursziele, keine Prognosen, keine Firmendetails, die nicht im Text "
    "stehen. Du gibst keine Kaufempfehlung. Du schreibst auf Deutsch, in ganzen Sätzen, "
    "ohne Fachbegriffe und ohne Werbesprache."
)

LLM_TASK = (
    "Schreibe aus den folgenden Stichpunkten drei kurze Sätze, die einem Anfänger "
    "erklären, was hier gemessen wurde. Jeder Satz nur EIN Gedanke, keine Verknüpfung "
    "von zwei Punkten. Format:\n"
    "GRUND: <Satz>\nGRUND: <Satz>\nGRUND: <Satz>"
)


def build_llm_prompt(opportunity: Opportunity) -> str:
    facts = "\n".join(f"- {line}" for line in opportunity.why_now)
    return (
        f"Titel: {opportunity.name} ({opportunity.ticker})\n"
        f"Anlass: {opportunity.headline}\n"
        f"Gemessene Punkte:\n{facts}\n"
        f"Gegenrede: {opportunity.risk}\n\n{LLM_TASK}"
    )


_GRUND_RE = re.compile(r"^\s*GRUND\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_ABER_RE = re.compile(r"^\s*ABER\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
# Wortlaut, den eine Meldung nie tragen darf: Empfehlung, Prognose, Garantie. Findet sich
# so etwas in der Modellantwort, wird die ganze Antwort verworfen statt repariert — ein
# halb gefiltertes Kaufversprechen ist gefährlicher als gar keins.
_FORBIDDEN = re.compile(
    r"\b(kaufempfehlung|ich empfehle|solltest du kaufen|garantiert|sicher(?:er)? gewinn|"
    r"wird steigen|wird fallen|verdoppel|kursziel von mir)\b",
    re.IGNORECASE,
)


def parse_llm_reply(raw: str) -> tuple[list[str], str | None]:
    """Modellantwort -> (Gründe, Gegenrede). Leer, wenn die Antwort nicht dem Format folgt
    oder verbotene Formulierungen enthält."""
    if not raw or _FORBIDDEN.search(raw):
        return [], None
    reasons = [m.strip() for m in _GRUND_RE.findall(raw) if len(m.strip()) > 15][:3]
    # Die ABER-Zeile wird noch gelesen (ältere Modellantworten und Tests kennen sie), aber
    # `polish` verwendet sie nicht mehr — siehe dort.
    aber = _ABER_RE.search(raw)
    counter = aber.group(1).strip() if aber and len(aber.group(1).strip()) > 15 else None
    if len(reasons) < 2:
        return [], None
    return reasons, counter


def polish(
    opportunity: Opportunity,
    *,
    ask: Callable[[str, str], str] | None = None,
) -> Opportunity:
    """Sprachlicher Schliff durchs LLM — mit Rückfall auf den Regel-Text bei allem, was
    schiefgehen kann (Modell aus, Zeitüberschreitung, Formatbruch, verbotener Wortlaut)."""
    if ask is None:
        return opportunity
    try:
        raw = ask(build_llm_prompt(opportunity), LLM_SYSTEM)
    except Exception:  # noqa: BLE001 - ein totes Modell darf keine Meldung kosten
        return opportunity
    reasons, _ = parse_llm_reply(raw or "")
    if not reasons:
        return opportunity
    from dataclasses import replace

    # Nur die GRÜNDE gehen durchs Modell, die Gegenrede nie. Live gemessen am 2026-08-27:
    # aus „Fällt der Kurs unter 18,91 $, ist die Idee widerlegt" machte qwen2.5:7b
    # „Der Screening-Verfahren-Kriteriumsnachweis unter der Qualitätsschwelle kann gegen
    # eine positive Bewertung arbeiten" — der Satz verlor die einzige konkrete Zahl der
    # Meldung und sagte nichts mehr. Die Gegenrede ist der Teil, an dem eine Meldung
    # ehrlich ist; sie ist der letzte Ort für eine Umformulierung auf gut Glück.
    return replace(opportunity, why_now=reasons, explained_by="llm")
