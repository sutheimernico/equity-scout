// Pure geometry for the 1-year price line on the phone card. Separate from the component
// so the maths is testable without a DOM, the same split ZoneBar/zone.ts already uses.

export interface Box {
  width: number;
  height: number;
  /** Vertical breathing room so the extreme points are not clipped by the stroke. */
  pad: number;
  /** Plot origin inside a larger viewBox — non-zero once axes claim space on the
   *  left and below. Defaults to 0/0 so a bare sparkline needs no offsets. */
  x?: number;
  y?: number;
}

/** SVG path through the series, scaled to the box. "" for fewer than two points. */
export function sparklinePath(closes: number[], box: Box): string {
  if (closes.length < 2) return "";
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min;
  const usable = box.height - 2 * box.pad;
  const originX = box.x ?? 0;
  const originY = box.y ?? 0;
  return closes
    .map((close, i) => {
      const x = originX + (i / (closes.length - 1)) * box.width;
      // A flat series has no span to scale against — centre it rather than divide by zero.
      const y =
        originY +
        (span === 0 ? box.height / 2 : box.pad + (1 - (close - min) / span) * usable);
      return `${i === 0 ? "M" : "L"} ${round(x)} ${round(y)}`;
    })
    .join(" ");
}

function round(value: number): number {
  // Two decimals keep the path string short without a visible kink at this size.
  return Math.round(value * 100) / 100;
}

/** Whole-percent return between the first and last close, or null when undefined.
 *  The backend guarantees these two are the real endpoints, not downsampled neighbours. */
export function yearReturnPct(closes: number[]): number | null {
  if (closes.length < 2 || closes[0] <= 0) return null;
  return Math.round((closes[closes.length - 1] / closes[0] - 1) * 100);
}

// --- Axes (2026-08-05: Nico wanted months on x and prices on y) --------------------

/** Deterministic German month abbreviations. Not `toLocaleDateString`: its short form
 *  varies by ICU build ("Sep" vs "Sept"), which would make the axis width unpredictable. */
const MONTHS_DE = [
  "Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
  "Jul", "Aug", "Sep", "Okt", "Nov", "Dez",
];

// Classic 1/2/5 ladder. No 2.5 step: it produces ticks like 1925 that read as noise next
// to 1900/1950, and the axis is only there to carry the values not directly labelled.
const NICE_STEPS = [1, 2, 5];

/** Clean y-axis values strictly inside [min,max], aiming for ~`target` ticks.
 *
 * Empty for a flat series: there is no range to label, and a lone tick on a flat line
 * states a precision the data does not have. If the first candidate yields fewer than two
 * ticks the ladder steps one finer — a single tick gives the reader no scale at all.
 */
export function priceTicks(min: number, max: number, target = 3): number[] {
  if (!(max > min)) return [];
  const ladder: number[] = [];
  const magnitude = Math.floor(Math.log10((max - min) / target));
  for (let exp = magnitude + 1; exp >= magnitude - 1; exp--) {
    for (let i = NICE_STEPS.length - 1; i >= 0; i--) {
      ladder.push(NICE_STEPS[i] * Math.pow(10, exp));
    }
  }
  // Coarsest first; take the first step that yields at least two ticks.
  let best: number[] = [];
  for (const step of ladder) {
    const ticks: number[] = [];
    for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) {
      // Guard the float drift that Math.ceil/+= accumulates on decimal steps.
      ticks.push(Number(v.toPrecision(12)));
    }
    const inside = ticks.filter((t) => t >= min && t <= max);
    if (inside.length >= 2) return inside;
    if (inside.length > best.length) best = inside;
  }
  return best;
}

export interface MonthTick {
  /** Index into the closes array — the first trading day of that month. */
  index: number;
  label: string;
}

/** One tick per `everyN`-th month, placed on the first stored day of that month.
 *
 * Placed on real indices rather than interpolated from the first/last date: trading days
 * are unevenly spaced, so an interpolated "1 March" lands next to the wrong price. Empty
 * without dates (cache rows written before the `dates` column) — the chart then draws
 * without a month axis instead of guessing.
 */
export function monthTicks(dates: string[], everyN = 3): MonthTick[] {
  if (dates.length === 0) return [];
  const firstOfMonth: MonthTick[] = [];
  let seen = "";
  dates.forEach((iso, index) => {
    const key = iso.slice(0, 7); // YYYY-MM
    if (key === seen) return;
    seen = key;
    const month = Number(iso.slice(5, 7));
    if (month >= 1 && month <= 12) firstOfMonth.push({ index, label: MONTHS_DE[month - 1] });
  });
  return firstOfMonth.filter((_, i) => i % everyN === 0);
}
