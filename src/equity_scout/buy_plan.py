"""Ein Titel, ein Kaufplan (Nachtschicht 2026-08-27).

Nicos Auftrag im Wortlaut: „langfristige Aktie, kurzfristige Aktie, am besten der Einkaufspreis
und dann Score und dann irgendwie ein guter Verkaufspreis, wann ich einfach nicht verkaufen
sollte, was für Tranchen ich einkaufen sollte, was das Unternehmen macht, warum es eine gute
Aktie ist, was News sind, ob sich irgendwelche Leute wie Kongressmitglieder gekauft haben."

Alle diese Angaben gab es schon — verteilt über Pitch-Text, Einstiegsplan, Brief-Karte,
Personenansicht und drei Endpunkte. Dieses Modul erfindet nichts dazu; es bündelt sie zu EINEM
Objekt pro Titel, in der Reihenfolge, in der man eine Kaufentscheidung trifft.

Vier Regeln, die den Bündel ehrlich halten:

- **Die Haltung („kaufbereit / warten / meiden") kommt aus der Kurslage zur Stützzone, nicht
  aus dem Score.** Ein Titel mit Score 69, dessen sämtliche Unterstützungen gebrochen sind,
  ist kein Kauf, und die Karte darf nicht anders klingen, nur weil die Zahl groß ist.
- **Ein fehlender Wert bleibt leer.** Kein Ersatzkursziel, keine geschätzte Nachricht, kein
  „0" für unbekannt — jede der Quellen hat ihre Lücken, und eine gefüllte Lücke ist die
  gefährlichste Angabe auf einer Karte, nach der jemand kauft.
- **Jeder Plan trägt die Bilanz seiner Quelle.** Der Kaufplan ist so viel wert wie das
  Verfahren, das ihn erzeugt hat; `track_record` hängt die gemessene Rückschau
  (`suggestion_review`) direkt an den Vorschlag, statt sie in einer Unterseite zu verstecken.
- **Der kurze Horizont wird als ungeprüft ausgewiesen.** Die Katalysator-Signale sind
  Beobachtungen aus dem Nachrichtenstrom, keine geprüften Einstiege — `evidence_state`
  sagt das an jeder einzelnen Karte, nicht in einer Fußnote.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from equity_scout.evidence.base import (
    SOURCE_13F,
    SOURCE_CONGRESS,
    SOURCE_INSIDER,
)
from equity_scout.exits import ExitRules

# Positionsobergrenze für einen Einzeltitel. Dieselbe Faustregel, die der Pitch-Text seit
# Juni nennt — hier als Zahl, damit die Oberfläche sie rechnen kann statt sie zu zitieren.
MAX_POSITION_SHARE_PCT = 5.0

# Ab wie weit über der Zone „warten" in „zu weit gelaufen" kippt. Deckungsgleich mit
# `frontend/src/aktien.ts`' NEAR_LIMIT: dieselbe Grenze darf nicht zweimal getippt werden.
NEAR_ZONE_LIMIT_PCT = 5.0

STANCE_READY = "kaufbereit"
STANCE_WAIT = "warten"
STANCE_FAR = "zu weit gelaufen"
STANCE_AVOID = "meiden"

_STANCE_NOTES = {
    STANCE_READY: "Kurs steht im Stützbereich — der Einstieg ist jetzt möglich.",
    STANCE_WAIT: "Knapp über dem Stützbereich. Mit Limit auf die Zone warten.",
    STANCE_FAR: "Deutlich über dem letzten Halt. Wer jetzt kauft, kauft nach einem Lauf.",
    STANCE_AVOID: "Alle Unterstützungen sind gefallen — kein Halt, an dem sich ein Limit "
                  "orientieren könnte.",
}


@dataclass(frozen=True)
class EntryGuidance:
    """Wo gekauft wird. `limit` ist die Zahl, die in die Order gehört — oder None."""

    stance: str
    stance_note: str
    limit: float | None
    zone_low: float
    zone_high: float
    gap_pct: float | None
    tranches: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ExitGuidance:
    """Wo verkauft wird — und ausdrücklich, wo NICHT."""

    target: float | None
    target_source: str | None
    stop: float | None
    analyst_target: float | None
    analyst_count: int | None
    hold_note: str
    profit_target_pct: float
    stop_loss_pct: float
    max_holding_days: int


@dataclass(frozen=True)
class Sizing:
    max_share_pct: float
    tranche_count: int
    note: str


@dataclass(frozen=True)
class BuyPlan:
    ticker: str
    name: str
    horizon: str            # "lang" | "kurz"
    evidence_state: str     # was die Messung über diese Quelle sagt
    score: int | None
    score_band: str | None
    price: float
    currency: str | None
    entry: EntryGuidance
    exit: ExitGuidance
    sizing: Sizing
    business: str | None
    why: list[str]
    news: list[dict]
    buyers: list[dict]
    tradability: dict
    track_record: dict | None

    def to_dict(self) -> dict:
        return asdict(self)


# Wer als KÄUFER zählt. Die Quellenkennungen werden aus `evidence.base` gespiegelt, nie
# getippt: dieselbe Konstante einmal abzuschreiben hat in `people.ts` drei tote Zweige und
# 80 falsch beschriftete Fondsmeldungen erzeugt (LOOP.md, 2026-08-23).
#
# `voice` ist ausdrücklich NICHT dabei. Eine Stimme im Nachrichtenstrom ist keine
# Kaufmeldung, und der Bestand zeigt, warum das mehr als eine Definitionsfrage ist: am
# 2026-08-26 hing „Warren Buffett" an einer Meldung über Meteoritenfunde in Medina County.
_BUYER_LABELS = {
    SOURCE_CONGRESS: ("Kongress", "politician"),
    SOURCE_INSIDER: ("Insider", "insider"),
    SOURCE_13F: ("Fonds (13F)", "fund"),
}


def buyers_from_events(events: list[dict]) -> list[dict]:
    """Gemeldete Käufe zu einem Titel, jüngste zuerst — die Antwort auf „wer hat gekauft".

    Meldungen sind verzögert: ein Kongress-Kauf erscheint bis zu 45 Tage später, eine
    13F-Position bis zu 45 Tage nach Quartalsende. `reported_at` steht deshalb neben
    `event_date`, damit die Karte kein frisches Kaufsignal vortäuscht.
    """
    buyers: list[dict] = []
    for event in events:
        label = _BUYER_LABELS.get(event.get("source", ""))
        if label is None:
            continue
        kind_label, person_field = label
        details = event.get("details") or {}
        buyers.append({
            "kind": kind_label,
            "source": event["source"],
            "person": details.get(person_field) or "unbekannt",
            "event_date": event.get("event_date"),
            "reported_at": details.get("filing_date") or details.get("filed_at"),
            "detail": details.get("change") or details.get("amount"),
        })
    return sorted(buyers, key=lambda b: b["event_date"] or "", reverse=True)


# Handelbarkeit für einen deutschen Privatanleger. Ein Kaufplan für einen Titel, den Nico
# gar nicht kaufen kann, ist kein Plan — und die Liste ist voll davon: unter den Top 10 vom
# 2026-08-26 standen drei indische Werte.
#
# Das ist eine EINSCHÄTZUNG nach Handelsplatz, keine Broker-Abfrage. Welche Börsen sein
# Depot bedient, weiß nur er; die Einordnung sagt, womit zu rechnen ist, und benennt sich
# selbst als das.
TRADABILITY_HOME = "heimisch"
TRADABILITY_EUROPE = "europäische Börse"
TRADABILITY_US = "US-Börse"
TRADABILITY_HARD = "schwer zugänglich"

_TRADABILITY_BY_SUFFIX = {
    ".DE": TRADABILITY_HOME, ".F": TRADABILITY_HOME,
    ".PA": TRADABILITY_EUROPE, ".AS": TRADABILITY_EUROPE, ".MI": TRADABILITY_EUROPE,
    ".MC": TRADABILITY_EUROPE, ".BR": TRADABILITY_EUROPE, ".VI": TRADABILITY_EUROPE,
    ".LS": TRADABILITY_EUROPE, ".L": TRADABILITY_EUROPE, ".SW": TRADABILITY_EUROPE,
    ".ST": TRADABILITY_EUROPE, ".CO": TRADABILITY_EUROPE, ".OL": TRADABILITY_EUROPE,
    ".HE": TRADABILITY_EUROPE,
    ".NS": TRADABILITY_HARD, ".BO": TRADABILITY_HARD, ".HK": TRADABILITY_HARD,
    ".SA": TRADABILITY_HARD, ".AX": TRADABILITY_HARD, ".TO": TRADABILITY_HARD,
    ".V": TRADABILITY_HARD, ".T": TRADABILITY_HARD,
}

_TRADABILITY_NOTES = {
    TRADABILITY_HOME: "Deutsche Notierung — über jedes Depot handelbar.",
    TRADABILITY_EUROPE: "Europäische Heimatbörse. Die meisten deutschen Broker bedienen sie; "
                        "je nach Depot mit Fremdbörsengebühr.",
    TRADABILITY_US: "US-Notierung. Über die üblichen Depots handelbar; bei sehr kleinen "
                    "Werten kann eine deutsche Zweitnotierung fehlen oder kaum Umsatz haben.",
    TRADABILITY_HARD: "Heimatbörse außerhalb Europas und der USA. Über deutsche "
                      "Standard-Depots meist gar nicht oder nur mit deutlichem Aufschlag "
                      "handelbar — vor dem Kauf im eigenen Depot prüfen.",
}


def tradability(ticker: str) -> dict:
    """Wo der Titel notiert und was das für ein deutsches Depot praktisch heißt."""
    for suffix, level in _TRADABILITY_BY_SUFFIX.items():
        if ticker.upper().endswith(suffix.upper()):
            return {"level": level, "note": _TRADABILITY_NOTES[level], "checked_broker": False}
    if "." in ticker:
        # Unbekannter Handelsplatz: das ist keine Freigabe, sondern eine Unbekannte.
        return {
            "level": TRADABILITY_HARD,
            "note": "Unbekannter Handelsplatz — vor dem Kauf im eigenen Depot prüfen.",
            "checked_broker": False,
        }
    return {
        "level": TRADABILITY_US,
        "note": _TRADABILITY_NOTES[TRADABILITY_US],
        "checked_broker": False,
    }


# Wie viele Schlagzeilen eine Karte trägt. Mehr macht aus der Kaufkarte einen Nachrichtenstrom.
MAX_NEWS = 5


def news_items(
    headlines: list[str] | None, headlines_de: list[str] | None
) -> list[dict]:
    """Schlagzeilen als (Original, Übersetzung) — das Original IMMER dabei.

    Warum nicht einfach die deutsche Fassung: die lokale Übersetzung (qwen2.5:7b) erfindet
    gelegentlich Inhalt. Zwei belegte Fälle vom 2026-08-26:

        „Euroholdings Ltd. (NASDAQ: EHLD) Stock Price, News & Analysis"
        -> „EHLD profitiert von starker Nachfrage nach Elektrifizierung — laut
           Analysten-Konsens"   (Reederei; Nachfrage, Elektrifizierung und Quelle erfunden)

        „Flat on the Stockholm stock market at midday"
        -> „S&P 500 ist stabil während der mittleren Börsensitzung am Mittag."
           (im Original kommt kein S&P 500 vor)

    Das ist maschinell nicht zuverlässig zu erkennen — die meisten Übersetzungen sind in
    Ordnung, und eine Heuristik auf Wortüberlappung markiert vor allem die korrekten. Also
    wird nicht gefiltert, sondern beigelegt: neben jeder deutschen Zeile steht die Quelle,
    an der man sie prüfen kann. Eine unbequeme englische Schlagzeile ist wahr, eine bequeme
    deutsche womöglich nicht — und hiernach wird gekauft.
    """
    originals = list(headlines or [])
    translations = list(headlines_de or [])
    items: list[dict] = []
    for i, original in enumerate(originals[:MAX_NEWS]):
        items.append({
            "headline": original,
            "de": translations[i] if i < len(translations) else None,
            "translation_note": "maschinell übersetzt — Original daneben prüfen",
        })
    return items


def stance_for(*, in_zone: bool, price: float, zone_low: float, zone_high: float) -> str:
    """Die Haltung folgt der Kurslage zur Stützzone — nie dem Score."""
    if in_zone:
        return STANCE_READY
    if price < zone_low:
        return STANCE_AVOID
    if zone_high > 0 and price <= zone_high * (1 + NEAR_ZONE_LIMIT_PCT / 100):
        return STANCE_WAIT
    return STANCE_FAR


def tranche_basis(stance: str, *, price: float, limit: float | None) -> float | None:
    """Der Kurs, ab dem die Tranchenleiter rechnet — oder None, wenn es keine geben darf.

    Am 2026-08-27 zeigte die erste Fassung dieser Karte für EHLD gleichzeitig „Limit 7,56"
    und „Tranche 1: jetzt bei 9,89". Zwei Zahlen, die einander widersprechen, auf einer
    Karte, nach der jemand kauft. Die Leiter hängt deshalb IMMER an der Zahl, die auch in
    die Order geht: im Stützbereich der aktuelle Kurs, darüber das Limit — und unter einer
    gebrochenen Zone gar keine, weil es dort keinen Einstieg zu staffeln gibt.
    """
    if stance == STANCE_AVOID:
        return None
    return price if stance == STANCE_READY else limit


def relabel_tranches(tranches: list[dict], *, at_limit: bool) -> list[dict]:
    """„Jetzt" heißt nur dann jetzt, wenn die Leiter am aktuellen Kurs hängt.

    Steht der Kurs über der Zone, rechnet die Leiter ab dem Limit — dann ist die erste
    Stufe kein „jetzt kaufen", sondern „kaufen, sobald das Limit erreicht ist". Ein Label,
    das zum Sofortkauf auffordert, während die Karte daneben „warten" sagt, ist derselbe
    Widerspruch wie die falsche Zahl, nur in Worten.
    """
    if not at_limit:
        return tranches
    return [
        {**t, "label": "bei Limit" if t["label"] == "Jetzt" else t["label"]}
        for t in tranches
    ]


def buy_limit_for(stance: str, *, price: float, zone_high: float) -> float | None:
    """Die Zahl, die in die Order gehört.

    Im Stützbereich ist der aktuelle Kurs kaufbar; darüber wartet man mit einem Limit auf die
    Zonenobergrenze. Unter der Zone gibt es KEIN Limit: die Marke, an der es sich orientieren
    würde, ist gerade gebrochen, und eine Zahl hinzuschreiben täuschte einen Halt vor.
    """
    if stance == STANCE_READY:
        return round(price, 2)
    if stance in (STANCE_WAIT, STANCE_FAR):
        return round(zone_high, 2)
    return None


def hold_note(target: float | None, stop: float | None, currency: str | None) -> str:
    """Der Satz zu „wann ich einfach nicht verkaufen sollte"."""
    unit = f" {currency}" if currency else ""
    if target is None or stop is None:
        return (
            "Kein Modell-Kursziel verfügbar. Ohne Ziel und Stop gilt die Grundregel: "
            f"nicht wegen Tagesbewegungen verkaufen, sondern erst bei {ExitRules().profit_target * 100:.0f} % "
            f"Gewinn oder {ExitRules().stop_loss * 100:.0f} % Verlust."
        )
    return (
        f"Zwischen {stop:.2f}{unit} und {target:.2f}{unit} halten — in diesem Band ist eine "
        "Kursbewegung normales Rauschen und kein Verkaufsgrund. Erst darunter oder darüber "
        "handeln."
    )


def why_lines(breakdown: dict | None, limit: int = 3) -> list[str]:
    """Die stärksten Faktoren im Klartext — die Antwort auf „warum ist das eine gute Aktie".

    Gelesen wird der gespeicherte Faktor-Breakdown des Screens, nicht eine LLM-Begründung:
    was den Titel nach oben gebracht hat, ist berechnet und muss auch so dastehen.
    """
    if not breakdown:
        return []
    scored = [
        (name, value) for name, value in breakdown.items()
        if isinstance(value, (int, float))
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [f"{name}: {value * 100:.0f}/100" for name, value in scored[:limit] if value > 0]


def build_plan(
    brief: dict,
    *,
    horizon: str = "lang",
    evidence_state: str,
    breakdown: dict | None = None,
    tranches: list[dict] | None = None,
    buyers: list[dict] | None = None,
    track_record: dict | None = None,
    rules: ExitRules | None = None,
) -> BuyPlan:
    """Ein Kaufplan aus einer Brief-Karte plus dem, was die anderen Speicher dazu haben.

    `brief` ist eine `briefs.build_brief`-Ausgabe: dieselbe Quelle, aus der die Aktienliste
    lebt. Damit können Liste und Kaufplan nicht auseinanderlaufen — ein Fehler, den dieses
    Repo an `people.ts` schon einmal bezahlt hat.
    """
    rules = rules or ExitRules()
    price = float(brief["price"])
    zone_low = float(brief["zone_low"])
    zone_high = float(brief["zone_high"])
    stance = stance_for(
        in_zone=bool(brief["in_zone"]), price=price, zone_low=zone_low, zone_high=zone_high
    )
    tranche_list = list(tranches or [])
    insight = brief.get("insight") or {}
    news = news_items(insight.get("headlines"), insight.get("headlines_de"))

    return BuyPlan(
        ticker=brief["ticker"],
        name=brief["name"],
        horizon=horizon,
        evidence_state=evidence_state,
        score=brief.get("score"),
        score_band=brief.get("score_band"),
        price=price,
        currency=brief.get("currency"),
        entry=EntryGuidance(
            stance=stance,
            stance_note=_STANCE_NOTES[stance],
            limit=buy_limit_for(stance, price=price, zone_high=zone_high),
            zone_low=zone_low,
            zone_high=zone_high,
            gap_pct=brief.get("zone_gap_pct"),
            tranches=tranche_list,
        ),
        exit=ExitGuidance(
            target=brief.get("model_target"),
            target_source=brief.get("target_source"),
            stop=brief.get("model_stop"),
            analyst_target=brief.get("analyst_target"),
            analyst_count=brief.get("analyst_count"),
            hold_note=hold_note(
                brief.get("model_target"), brief.get("model_stop"), brief.get("currency")
            ),
            profit_target_pct=rules.profit_target * 100,
            stop_loss_pct=rules.stop_loss * 100,
            max_holding_days=rules.max_holding_days,
        ),
        sizing=Sizing(
            max_share_pct=MAX_POSITION_SHARE_PCT,
            tranche_count=len(tranche_list),
            note=(
                f"Höchstens {MAX_POSITION_SHARE_PCT:.0f} % des Anlagevermögens in diesen "
                f"einen Titel, verteilt auf {len(tranche_list)} Schritte."
                if tranche_list else
                f"Höchstens {MAX_POSITION_SHARE_PCT:.0f} % des Anlagevermögens in diesen "
                "einen Titel."
            ),
        ),
        business=insight.get("business"),
        why=why_lines(breakdown),
        news=news,
        buyers=list(buyers or []),
        tradability=tradability(brief["ticker"]),
        track_record=track_record,
    )


def sort_plans(plans: list[BuyPlan]) -> list[BuyPlan]:
    """Kaufbereit zuerst, dann nach Score — dieselbe Ordnung wie `briefs.rank_entries`."""
    order = {STANCE_READY: 0, STANCE_WAIT: 1, STANCE_FAR: 2, STANCE_AVOID: 3}
    return sorted(plans, key=lambda p: (order[p.entry.stance], -(p.score or 0)))
