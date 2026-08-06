export type View =
  | "today"
  | "funnel"
  | "radar"
  | "voices"
  | "inbox"
  | "depots"
  | "proof"
  | "strategies"
  | "model"
  | "ml"
  | "learning"
  | "chat";

// v6 IA (plan P6): visible group labels instead of an anonymous hairline, a "Heute" start
// page, all paper depots under ONE nav item, and unambiguous German names — "Entry-Modell"
// vs "Signal-Filter" ends the old Modell/Meta-Modell collision.
export type Group = "start" | "signale" | "entscheiden" | "forschung" | "mehr";

export const GROUP_LABELS: Record<Group, string> = {
  start: "",
  signale: "Signale",
  entscheiden: "Entscheiden",
  forschung: "Forschung",
  mehr: "",
};

export const NAV: { key: View; label: string; group: Group }[] = [
  { key: "today", label: "Heute", group: "start" },
  { key: "funnel", label: "Screener", group: "signale" },
  { key: "radar", label: "Radar", group: "signale" },
  { key: "voices", label: "Stimmen", group: "signale" },
  { key: "inbox", label: "Inbox", group: "entscheiden" },
  { key: "depots", label: "Depots", group: "entscheiden" },
  { key: "proof", label: "Ergebnisse", group: "entscheiden" },
  { key: "strategies", label: "Strategien", group: "forschung" },
  { key: "model", label: "Entry-Modell", group: "forschung" },
  { key: "ml", label: "Signal-Filter", group: "forschung" },
  { key: "learning", label: "Lernkurven", group: "forschung" },
  { key: "chat", label: "Assistent", group: "mehr" },
];

// The phone gets four tabs; everything else lives behind "Mehr". Order is the tab order.
export const MOBILE_FOCUSES: View[] = ["today", "depots", "inbox", "proof"];

export const MOBILE_LABELS: Record<string, string> = {
  today: "Heute",
  depots: "Depot",
  inbox: "Entscheiden",
  proof: "Ergebnisse",
};

const VIEW_KEYS = new Set<string>(NAV.map((item) => item.key));

/** `?view=depots` -> "depots"; anything unknown or absent -> "today".
 *  Deliberately forgiving: a stale Telegram deep link must land somewhere sensible. */
export function parseView(search: string): View {
  const raw = new URLSearchParams(search).get("view");
  return raw && VIEW_KEYS.has(raw) ? (raw as View) : "today";
}
