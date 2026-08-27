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
    news: list[str]
    buyers: list[dict]
    track_record: dict | None

    def to_dict(self) -> dict:
        return asdict(self)


def stance_for(*, in_zone: bool, price: float, zone_low: float, zone_high: float) -> str:
    """Die Haltung folgt der Kurslage zur Stützzone — nie dem Score."""
    if in_zone:
        return STANCE_READY
    if price < zone_low:
        return STANCE_AVOID
    if zone_high > 0 and price <= zone_high * (1 + NEAR_ZONE_LIMIT_PCT / 100):
        return STANCE_WAIT
    return STANCE_FAR


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
    headlines = insight.get("headlines_de") or insight.get("headlines") or []

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
        news=list(headlines)[:5],
        buyers=list(buyers or []),
        track_record=track_record,
    )


def sort_plans(plans: list[BuyPlan]) -> list[BuyPlan]:
    """Kaufbereit zuerst, dann nach Score — dieselbe Ordnung wie `briefs.rank_entries`."""
    order = {STANCE_READY: 0, STANCE_WAIT: 1, STANCE_FAR: 2, STANCE_AVOID: 3}
    return sorted(plans, key=lambda p: (order[p.entry.stance], -(p.score or 0)))
