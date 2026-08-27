// Darstellungslogik der Kaufplan-Ansicht (Nachtschicht 2026-08-27).
//
// Alles, was hier steht, ist bewusst KEIN React: die Regeln, nach denen eine Kaufkarte
// eingefärbt, sortiert und beschriftet wird, gehören unter Test. Die Rechnung selbst
// (Limit, Haltung, Tranchen) macht das Backend — hier wird nur entschieden, wie sie
// aussieht, und zwar so, dass die Farbe nie etwas anderes behauptet als der Text.

import type { BuyPlan, Stance, TrackRecord } from "./api";

/** Die vier Haltungen, gespiegelt aus `buy_plan.py`. Ein umbenannter Wert fällt beim
 *  Bauen auf, statt still einen toten Zweig zu hinterlassen (people.ts-Lehre). */
export const STANCES: Stance[] = ["kaufbereit", "warten", "zu weit gelaufen", "meiden"];

export interface StanceMeta {
  label: string;
  chip: string;
  /** Kurzform für die Kopfzeile der Karte — nie mehr als drei Wörter. */
  short: string;
}

export const STANCE_META: Record<Stance, StanceMeta> = {
  kaufbereit: { label: "Kaufbereit", chip: "plan-chip plan-chip-ready", short: "jetzt möglich" },
  warten: { label: "Warten", chip: "plan-chip plan-chip-wait", short: "Limit setzen" },
  "zu weit gelaufen": {
    label: "Zu weit gelaufen",
    chip: "plan-chip plan-chip-far",
    short: "nach dem Lauf",
  },
  meiden: { label: "Meiden", chip: "plan-chip plan-chip-avoid", short: "kein Halt" },
};

/** Filtersegmente der Ansicht. "handelbar" blendet aus, was Nico ohnehin nicht kaufen kann. */
export type PlanFilter = "kaufbar" | "handelbar" | "alle";

export const PLAN_FILTERS: { key: PlanFilter; label: string }[] = [
  { key: "kaufbar", label: "Kaufbereit" },
  { key: "handelbar", label: "Erreichbar" },
  { key: "alle", label: "Alle" },
];

/** Handelsplätze, die ein deutsches Standard-Depot in aller Regel NICHT bedient. */
const HARD_TO_REACH = "schwer zugänglich";

export function isReachable(plan: BuyPlan): boolean {
  return plan.tradability.level !== HARD_TO_REACH;
}

export function filterPlans(plans: BuyPlan[], filter: PlanFilter): BuyPlan[] {
  if (filter === "alle") return plans;
  if (filter === "handelbar") return plans.filter(isReachable);
  return plans.filter((plan) => plan.entry.stance === "kaufbereit");
}

/** Was die Ansicht sagt, wenn ein Filter nichts übrig lässt.
 *
 *  Ein leerer Zustand ist hier ein ERGEBNIS, keine Panne: am 2026-08-26 stand kein
 *  einziger der 30 Titel im Stützbereich. Der Text sagt das und schickt den Leser
 *  weiter, statt eine leere Fläche zu zeigen. */
export function emptyNote(filter: PlanFilter, total: number): string {
  if (total === 0) return "Noch keine Watchlist berechnet.";
  if (filter === "kaufbar") {
    return `Kein Titel steht gerade im Stützbereich. Das ist ein Befund, kein Fehler — bei ${total} geprüften Titeln heißt es: heute nichts kaufen. Unter „Alle“ siehst du, wo die Limits liegen.`;
  }
  if (filter === "handelbar") {
    return "Alle aktuellen Titel notieren außerhalb Europas und der USA — über ein deutsches Standard-Depot meist nicht erreichbar.";
  }
  return "Keine Titel.";
}

/** Kopfzeile: was diese Liste insgesamt wert war. Null, solange nie gemessen wurde. */
export function trackRecordLine(record: TrackRecord | null): string | null {
  if (record === null) return null;
  if (record.mean_excess_pct === null) {
    return `Bilanz dieser Liste: ${record.n_independent} ausgewertete Vorschläge, aber kein Vergleichsmaßstab.`;
  }
  const sign = record.mean_excess_pct >= 0 ? "+" : "−";
  const value = Math.abs(record.mean_excess_pct).toFixed(1);
  const hit =
    record.hit_rate === null ? "" : `, ${Math.round(record.hit_rate * 100)} % im Plus`;
  return `Bilanz dieser Liste: ${sign}${value} Prozentpunkte gegen den Heimatindex über ${record.n_independent} Vorschläge${hit}.`;
}

/** Abstand zum Kauflimit in Prozent — die Zahl, die „wie weit noch?" beantwortet.
 *  Null, wenn es kein Limit gibt: unter einer gebrochenen Zone ist der Abstand bedeutungslos. */
export function distanceToLimitPct(plan: BuyPlan): number | null {
  const limit = plan.entry.limit;
  if (limit === null || limit <= 0 || plan.price <= 0) return null;
  return (plan.price / limit - 1) * 100;
}

/** Was eine Tranche in Euro bedeutet, wenn das Depot `portfolioValue` groß ist.
 *
 *  Ohne Depotgröße gibt es keine Zahl — eine erfundene Bezugsgröße wäre die
 *  gefährlichste Angabe auf einer Karte, nach der jemand kauft. */
export function tranchePositionEur(
  plan: BuyPlan,
  share: number,
  portfolioValue: number | null,
): number | null {
  if (portfolioValue === null || portfolioValue <= 0) return null;
  return (portfolioValue * plan.sizing.max_share_pct) / 100 * share;
}

/** Zusammenfassung der gemeldeten Käufer für die Kartenzeile ("2 Kongress, 1 Fonds"). */
export function buyerSummary(plan: BuyPlan): string | null {
  if (plan.buyers.length === 0) return null;
  const counts = new Map<string, number>();
  for (const buyer of plan.buyers) {
    counts.set(buyer.kind, (counts.get(buyer.kind) ?? 0) + 1);
  }
  return [...counts.entries()].map(([kind, n]) => `${n}× ${kind}`).join(", ");
}
