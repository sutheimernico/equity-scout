// Geometry for the entry-zone bullet bar (2026-08-04: "Zielbereich nicht mit Text
// sondern so Balken"). Pure math, no DOM — the component only positions what this
// returns.
//
// The window is the zone widened by one zone-width on each side, so the zone is ALWAYS
// the middle third of the bar. That is a deliberate trade: the axis measures distance in
// zone-widths, not in currency, so two cards are comparable and a far-out price cannot
// squeeze the zone into a hairline (Micron sits 70 % above its zone — on a
// price-proportional axis its zone would be ~3 px wide and unreadable). The absolute
// numbers stay legible because the zone bounds are printed under the bar edges and the
// verdict line carries the real percentage.

/** The zone occupies the middle third — derived from the ±1-zone-width window. */
export const ZONE_START_PCT = 100 / 3;
export const ZONE_END_PCT = 200 / 3;

/** How far a marker may sit from the edge before it would hang off the bar. */
const MARKER_INSET_PCT = 2;

export type Overflow = "low" | "high" | null;

export interface ZoneGeometry {
  /** 0–100 along the bar; inset from the edges so the marker never clips. */
  pricePct: number;
  /** Set when the price is outside the window — render a directional arrow, not a marker. */
  priceOverflow: Overflow;
  /** 0–100, or null when there is no target or it falls outside the window. */
  targetPct: number | null;
}

function isUsableNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * Returns null when the inputs cannot honestly be drawn — a non-positive price, a
 * collapsed or inverted zone. The caller then falls back to the text-only verdict
 * rather than drawing a bar whose geometry would be invented.
 */
export function zoneGeometry(
  price: number,
  zoneLow: number,
  zoneHigh: number,
  target: number | null = null,
): ZoneGeometry | null {
  if (!isUsableNumber(price) || price <= 0) return null;
  if (!isUsableNumber(zoneLow) || !isUsableNumber(zoneHigh)) return null;

  const width = zoneHigh - zoneLow;
  if (width <= 0) return null; // collapsed or inverted zone — nothing to scale against

  const windowLow = zoneLow - width;
  const span = width * 3;
  const pctOf = (value: number) => ((value - windowLow) / span) * 100;

  const rawPrice = pctOf(price);
  let priceOverflow: Overflow = null;
  if (rawPrice < 0) priceOverflow = "low";
  else if (rawPrice > 100) priceOverflow = "high";

  const rawTarget = isUsableNumber(target) && target > 0 ? pctOf(target) : null;

  return {
    // Overflow arrows sit flush on the edge; in-window markers keep an inset so their
    // ring stays inside the track.
    pricePct:
      priceOverflow === "low"
        ? 0
        : priceOverflow === "high"
          ? 100
          : clamp(rawPrice, MARKER_INSET_PCT, 100 - MARKER_INSET_PCT),
    priceOverflow,
    // A target outside the window is dropped rather than pinned to the edge: two arrows
    // on one edge read as a single smear, and the upside line already states the number.
    targetPct:
      rawTarget !== null && rawTarget >= 0 && rawTarget <= 100
        ? clamp(rawTarget, MARKER_INSET_PCT, 100 - MARKER_INSET_PCT)
        : null,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * The fewest decimals at which the two zone bounds still read as different numbers.
 * A fixed 0 decimals would print a 2.10–2.35 penny-stock zone as "2" twice; a fixed 2
 * would waste width on a 3.135–4.057 JPY zone under a 390 px card.
 */
export function boundDigits(zoneLow: number, zoneHigh: number, max = 4): number {
  for (let digits = 0; digits < max; digits += 1) {
    if (zoneLow.toFixed(digits) !== zoneHigh.toFixed(digits)) return digits;
  }
  return max;
}

/** Zone bound for the scale under the bar — de-DE grouping, no currency (the price above carries it). */
export function formatBound(value: number, digits: number): string {
  return value.toLocaleString("de-DE", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
