import { describe, expect, it } from "vitest";

import type { BuyPlan, TrackRecord } from "./api";
import {
  STANCES,
  STANCE_META,
  buyerSummary,
  distanceToLimitPct,
  emptyNote,
  filterPlans,
  isReachable,
  tranchePositionEur,
  trackRecordLine,
} from "./kaufplan";

function plan(overrides: Partial<BuyPlan> = {}): BuyPlan {
  return {
    ticker: "TEST",
    name: "Test AG",
    horizon: "lang",
    evidence_state: "x",
    score: 60,
    score_band: "mittel",
    price: 100,
    currency: "EUR",
    entry: {
      stance: "kaufbereit",
      stance_note: "",
      limit: 100,
      zone_low: 90,
      zone_high: 110,
      gap_pct: 0,
      tranches: [],
    },
    exit: {
      target: 120,
      target_source: "model",
      stop: 85,
      analyst_target: null,
      analyst_count: null,
      hold_note: "",
      profit_target_pct: 20,
      stop_loss_pct: 15,
      max_holding_days: 180,
    },
    sizing: { max_share_pct: 5, tranche_count: 0, note: "" },
    business: null,
    why: [],
    news: [],
    buyers: [],
    tradability: { level: "US-Börse", note: "", checked_broker: false },
    track_record: null,
    ...overrides,
  };
}

describe("Haltungen", () => {
  it("hat für jede Haltung des Backends eine Darstellung", () => {
    // Fehlt eine, rendert die Karte undefined statt eines Chips.
    for (const stance of STANCES) {
      expect(STANCE_META[stance]).toBeDefined();
      expect(STANCE_META[stance].label.length).toBeGreaterThan(0);
    }
  });

  it("gibt jeder Haltung eine eigene Chip-Klasse", () => {
    const chips = new Set(STANCES.map((s) => STANCE_META[s].chip));
    expect(chips.size).toBe(STANCES.length);
  });
});

describe("Filter", () => {
  it("zeigt unter „Kaufbereit“ nur, was im Stützbereich steht", () => {
    const plans = [
      plan({ ticker: "A", entry: { ...plan().entry, stance: "kaufbereit" } }),
      plan({ ticker: "B", entry: { ...plan().entry, stance: "warten" } }),
    ];
    expect(filterPlans(plans, "kaufbar").map((p) => p.ticker)).toEqual(["A"]);
  });

  it("blendet unter „Erreichbar“ aus, was ein deutsches Depot nicht bedient", () => {
    const plans = [
      plan({ ticker: "US", tradability: { level: "US-Börse", note: "", checked_broker: false } }),
      plan({
        ticker: "IN",
        tradability: { level: "schwer zugänglich", note: "", checked_broker: false },
      }),
    ];
    expect(filterPlans(plans, "handelbar").map((p) => p.ticker)).toEqual(["US"]);
  });

  it("lässt unter „Alle“ nichts weg", () => {
    const plans = [plan({ ticker: "A" }), plan({ ticker: "B" })];
    expect(filterPlans(plans, "alle")).toHaveLength(2);
  });

  it("hält einen indischen Titel für nicht erreichbar", () => {
    const hard = plan({
      tradability: { level: "schwer zugänglich", note: "", checked_broker: false },
    });
    expect(isReachable(hard)).toBe(false);
    expect(isReachable(plan())).toBe(true);
  });
});

describe("Leerer Zustand", () => {
  it("erklärt eine leere Kaufliste als Befund, nicht als Panne", () => {
    // Der reale Stand am 2026-08-26: 30 geprüfte Titel, 0 im Stützbereich.
    const note = emptyNote("kaufbar", 30);
    expect(note).toContain("30 geprüften Titeln");
    expect(note).toContain("kein Fehler");
  });

  it("sagt bei leerer Watchlist etwas anderes als bei leerem Filter", () => {
    expect(emptyNote("kaufbar", 0)).toContain("Noch keine Watchlist");
  });

  it("benennt beim Erreichbarkeitsfilter den Grund", () => {
    expect(emptyNote("handelbar", 30)).toContain("deutsches Standard-Depot");
  });
});

describe("Bilanz der Liste", () => {
  const record = (over: Partial<TrackRecord> = {}): TrackRecord => ({
    computed_at: "2026-08-27T00:07:21+00:00",
    n_independent: 15,
    hit_rate: 0.6,
    mean_excess_pct: 0.08,
    line: "",
    ...over,
  });

  it("zeigt nichts an, solange nie gemessen wurde", () => {
    expect(trackRecordLine(null)).toBeNull();
  });

  it("nennt Vorzeichen, Höhe, Trefferquote und n", () => {
    const line = trackRecordLine(record({ mean_excess_pct: 2.2, hit_rate: 0.67 }));
    expect(line).toContain("+2.2 Prozentpunkte");
    expect(line).toContain("67 % im Plus");
    expect(line).toContain("15 Vorschläge");
  });

  it("stellt eine negative Bilanz genauso deutlich dar wie eine positive", () => {
    expect(trackRecordLine(record({ mean_excess_pct: -1.4 }))).toContain("−1.4 Prozentpunkte");
  });

  it("sagt es, wenn ein Vergleichsmaßstab fehlt, statt null zu rechnen", () => {
    const line = trackRecordLine(record({ mean_excess_pct: null }));
    expect(line).toContain("kein Vergleichsmaßstab");
  });
});

describe("Abstand zum Limit", () => {
  it("rechnet, wie weit der Kurs über dem Limit steht", () => {
    const far = plan({ price: 9.89, entry: { ...plan().entry, limit: 7.56 } });
    expect(distanceToLimitPct(far)).toBeCloseTo(30.8, 1);
  });

  it("ist null, wenn es kein Limit gibt", () => {
    // Unter einer gebrochenen Zone ist der Abstand zu einem Limit bedeutungslos.
    expect(distanceToLimitPct(plan({ entry: { ...plan().entry, limit: null } }))).toBeNull();
  });

  it("ist null bei einem unbrauchbaren Kurs, statt durch null zu teilen", () => {
    expect(distanceToLimitPct(plan({ price: 0 }))).toBeNull();
  });
});

describe("Tranchengröße in Euro", () => {
  it("rechnet Anteil mal Positionsdeckel mal Depotwert", () => {
    // 10.000 € Depot, 5 % Deckel = 500 €, ein Drittel davon = 166,67 €.
    expect(tranchePositionEur(plan(), 1 / 3, 10_000)).toBeCloseTo(166.67, 1);
  });

  it("gibt ohne bekannte Depotgröße keine Zahl aus", () => {
    // Eine erfundene Bezugsgröße wäre die gefährlichste Angabe auf dieser Karte.
    expect(tranchePositionEur(plan(), 1 / 3, null)).toBeNull();
    expect(tranchePositionEur(plan(), 1 / 3, 0)).toBeNull();
  });
});

describe("Käufer-Zusammenfassung", () => {
  it("zählt je Art", () => {
    const withBuyers = plan({
      buyers: [
        { kind: "Kongress", source: "congress", person: "A", event_date: "2026-08-01", reported_at: null, detail: null },
        { kind: "Kongress", source: "congress", person: "B", event_date: "2026-08-02", reported_at: null, detail: null },
        { kind: "Fonds (13F)", source: "thirteen_f", person: "C", event_date: "2026-08-03", reported_at: null, detail: null },
      ],
    });
    expect(buyerSummary(withBuyers)).toBe("2× Kongress, 1× Fonds (13F)");
  });

  it("gibt null zurück, wenn niemand gemeldet ist", () => {
    // Nicht "0 Käufer": die Karte soll die Zeile dann ganz weglassen.
    expect(buyerSummary(plan())).toBeNull();
  });
});
