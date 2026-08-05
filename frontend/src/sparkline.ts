// Pure geometry for the 1-year price line on the phone card. Separate from the component
// so the maths is testable without a DOM, the same split ZoneBar/zone.ts already uses.

export interface Box {
  width: number;
  height: number;
  /** Vertical breathing room so the extreme points are not clipped by the stroke. */
  pad: number;
}

/** SVG path through the series, scaled to the box. "" for fewer than two points. */
export function sparklinePath(closes: number[], box: Box): string {
  if (closes.length < 2) return "";
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min;
  const usable = box.height - 2 * box.pad;
  return closes
    .map((close, i) => {
      const x = (i / (closes.length - 1)) * box.width;
      // A flat series has no span to scale against — centre it rather than divide by zero.
      const y =
        span === 0 ? box.height / 2 : box.pad + (1 - (close - min) / span) * usable;
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
