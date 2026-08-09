// v7 IA (cockpit rebuild 2026-08-07, mockup v2): five phone tabs — Heute · Aktien ·
// Entscheiden · Depot · Mehr — plus the stock profile as its own routed view. The old
// 13-view nav folds into this without deleting anything: research views live under
// Labor, Personen + Stimmen under "Wer kauft?", Ergebnisse moves out of the bottom bar
// into Mehr, and the assistant becomes a chat overlay behind a FAB on every screen.
export type View =
  | "heute"
  | "aktien"
  | "profil"
  | "entscheiden"
  | "depot"
  | "ergebnisse"
  | "werkauft"
  | "labor"
  | "wie";

export type Group = "start" | "mehr";

export const GROUP_LABELS: Record<Group, string> = {
  start: "",
  mehr: "Mehr",
};

// "profil" is deliberately NOT a NAV entry: it is a routed drill-down reached from
// lists, never a place the nav points to.
export const NAV: { key: View; label: string; group: Group }[] = [
  { key: "heute", label: "Heute", group: "start" },
  { key: "aktien", label: "Aktien", group: "start" },
  { key: "entscheiden", label: "Entscheiden", group: "start" },
  { key: "depot", label: "Depot", group: "start" },
  { key: "ergebnisse", label: "Ergebnisse", group: "mehr" },
  { key: "werkauft", label: "Wer kauft?", group: "mehr" },
  { key: "wie", label: "Wie funktioniert das?", group: "mehr" },
  { key: "labor", label: "Labor", group: "mehr" },
];

// The phone's four fixed tabs; everything in the "mehr" group lives in the sheet.
export const MOBILE_FOCUSES: View[] = ["heute", "aktien", "entscheiden", "depot"];

export const MOBILE_LABELS: Record<string, string> = {
  heute: "Heute",
  aktien: "Aktien",
  entscheiden: "Entscheiden",
  depot: "Depot",
};

/** One-line descriptions for the Mehr sheet (mockup wording). */
export const SHEET_NOTES: Record<string, string> = {
  ergebnisse: "Funktioniert das alles? Die ehrliche Auswertung.",
  werkauft: "Politiker, Insider, Fonds & bekannte Stimmen.",
  wie: "Die App in sechs einfachen Antworten.",
  labor: "Strategien, Modelle, Lernkurven — und Daten aktualisieren.",
};

/** Pre-v7 view keys → their new home, so old Telegram deep links keep landing
 *  somewhere sensible. "chat" maps to heute; parseChatOpen opens the overlay. */
const LEGACY_VIEWS: Record<string, View> = {
  today: "heute",
  funnel: "aktien",
  radar: "aktien",
  voices: "werkauft",
  people: "werkauft",
  inbox: "entscheiden",
  depots: "depot",
  proof: "ergebnisse",
  strategies: "labor",
  model: "labor",
  ml: "labor",
  learning: "labor",
  chat: "heute",
};

const VIEW_KEYS = new Set<string>([...NAV.map((item) => item.key), "profil"]);

/** Any string (new key, legacy key, garbage) → a valid View. */
export function resolveView(key: string): View {
  if (VIEW_KEYS.has(key)) return key as View;
  return LEGACY_VIEWS[key] ?? "heute";
}

// Same shape the backend enforces on /api/stack/{ticker}.
const TICKER_RE = /^[A-Za-z0-9.\-]{1,12}$/;

/** `?ticker=mu` -> "MU"; absent or implausible -> null. */
export function parseTicker(search: string): string | null {
  const raw = new URLSearchParams(search).get("ticker");
  return raw && TICKER_RE.test(raw) ? raw.toUpperCase() : null;
}

/** The chat overlay lives in the URL (`?chat=1`) so the phone's back gesture closes
 *  it; a legacy `?view=chat` deep link opens it too. */
export function parseChatOpen(search: string): boolean {
  const params = new URLSearchParams(search);
  return params.get("chat") === "1" || params.get("view") === "chat";
}

/** `?view=depot` -> "depot"; legacy keys map to their new home; anything unknown or
 *  absent -> "heute". A profile link without a plausible ticker lands on the list. */
export function parseView(search: string): View {
  const raw = new URLSearchParams(search).get("view");
  const view = raw ? resolveView(raw) : "heute";
  if (view === "profil" && parseTicker(search) === null) return "aktien";
  return view;
}
