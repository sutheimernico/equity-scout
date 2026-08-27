// Die Entscheidungslogik der Startseiten-Karte, getrennt von React, damit sie prüfbar ist:
// „Muss ich heute etwas tun?" ist die eine Frage, an der die Karte gemessen wird.

export interface TodaySignal {
  notified_at: string;
  stance: string | null;
}

/** Nur HEUTE gemeldete Chancen zählen. Eine Meldung von vorgestern ist Verlauf, keine
 *  Handlungsaufforderung — sonst stünde die Karte tagelang auf „eine Chance wartet". */
export function todaysSignals<T extends TodaySignal>(rows: T[], today: string): T[] {
  return rows.filter((row) => row.notified_at.slice(0, 10) === today.slice(0, 10));
}

export type TodayVerdict = "kaufbereit" | "entscheiden" | "bald" | "ruhig";

/** Was die Karte sagt. Reihenfolge = Dringlichkeit: etwas, das heute handelbar ist,
 *  schlägt eine offene Entscheidung, und die schlägt einen Limit-Hinweis. */
export function todayVerdict(input: {
  ready: number;
  decisions: number;
  soon: number;
}): TodayVerdict {
  if (input.ready > 0) return "kaufbereit";
  if (input.decisions > 0) return "entscheiden";
  if (input.soon > 0) return "bald";
  return "ruhig";
}
