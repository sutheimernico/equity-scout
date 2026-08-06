// What the long-term book actually holds, in plain German.
//
// Nico 2026-08-06: "da steht ja immer noch BIL, IEF, aber ich kann damit ja nichts
// anfangen … ich hätte immer gerne auch eine Ebene tiefer, wo die erläutert werden."
// A ticker is not information: "IEF" says nothing, "US-Staatsanleihen mit 7–10 Jahren
// Laufzeit" does.
//
// Hard-coded on purpose rather than fetched: this is the auto-depot's fixed 21-ETF basket
// (see data/etf_universe), the descriptions do not change, and a lookup would put a
// network call behind a tap that must be instant. A ticker missing here renders an honest
// "keine Kurzbeschreibung hinterlegt" instead of a guess.

export interface EtfNote {
  name: string;
  what: string;
}

// Nico 2026-08-06: "dass dieser High dann halt auch zumindest bei den plus zehn Prozent
// oder plus fünf Prozent da irgendwie Namen drinstehen."
//
// Only the large holdings carry their name in the row: the book holds eleven positions, and
// a second line on every one of them turns the list back into the wall that the 05.08.
// rebuild removed. The small ones keep the name behind the tap.
export const NAME_IN_ROW_WEIGHT = 0.05;

/** The plain name to show in the row itself, or null — either because the holding is small
 *  or because no description is on file. Never a guessed name. */
export function rowName(ticker: string, weight: number): string | null {
  if (Math.abs(weight) < NAME_IN_ROW_WEIGHT) return null;
  return ETF_NOTES[ticker]?.name ?? null;
}

export const ETF_NOTES: Record<string, EtfNote> = {
  SPY: { name: "S&P 500", what: "die 500 größten US-Unternehmen, nach Börsenwert gewichtet." },
  IEF: {
    name: "US-Staatsanleihen 7–10 J.",
    what: "mittellang laufende Anleihen des US-Staats — der klassische Gegenpol zu Aktien.",
  },
  VEU: {
    name: "Welt ohne USA",
    what: "Aktien aus Europa, Japan, Schwellenländern — alles außer den USA.",
  },
  BIL: {
    name: "US-Geldmarkt 1–3 Mon.",
    what: "kürzeste Staatsanleihen, praktisch Parkplatz für Bargeld.",
  },
  TLT: {
    name: "US-Staatsanleihen 20+ J.",
    what: "sehr lang laufende Anleihen — reagieren stark auf Zinsänderungen.",
  },
  GLD: { name: "Gold", what: "physisch hinterlegtes Gold." },
  DBC: {
    name: "Rohstoffkorb",
    what: "Öl, Gas, Metalle und Agrarrohstoffe über Terminkontrakte.",
  },
  VNQ: { name: "US-Immobilien", what: "börsennotierte US-Immobiliengesellschaften (REITs)." },
  XLE: { name: "Energie (S&P)", what: "US-Öl-, Gas- und Energiekonzerne." },
  XLK: { name: "Technologie (S&P)", what: "US-Technologiewerte, Software und Halbleiter." },
  XLV: { name: "Gesundheit (S&P)", what: "US-Pharma, Medizintechnik und Krankenversicherer." },
  XLF: { name: "Finanzen (S&P)", what: "US-Banken, Versicherer und Vermögensverwalter." },
  XLI: { name: "Industrie (S&P)", what: "US-Maschinenbau, Luftfahrt, Transport und Bau." },
  XLP: {
    name: "Basiskonsum (S&P)",
    what: "Lebensmittel, Getränke, Haushaltswaren — Nachfrage schwankt kaum.",
  },
  XLY: {
    name: "Zykl. Konsum (S&P)",
    what: "Autos, Handel, Reisen — hängt am Konsumklima.",
  },
  XLU: { name: "Versorger (S&P)", what: "Strom-, Gas- und Wasserversorger." },
  XLB: { name: "Grundstoffe (S&P)", what: "Chemie, Baustoffe, Bergbau, Verpackung." },
  XLC: {
    name: "Kommunikation (S&P)",
    what: "Telekom, Medien und die großen Plattformkonzerne.",
  },
  XLRE: { name: "Immobilien (S&P)", what: "US-Immobilienwerte innerhalb des S&P 500." },
  EEM: { name: "Schwellenländer", what: "Aktien aus China, Indien, Brasilien und weiteren." },
  EFA: { name: "Industrieländer ex USA", what: "Aktien aus Europa, Japan, Australien." },
};
