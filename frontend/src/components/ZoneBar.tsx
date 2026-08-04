import type { StockBrief } from "../api";
import { boundDigits, formatBound, zoneGeometry } from "../zone";

// The entry zone as a bullet bar instead of a sentence (2026-08-04: Nico wanted the target
// range visual, not textual). Three fixed bands — cheaper than the zone · good entry ·
// more expensive than the zone — with the current price as the loud marker and the
// analyst target as a quiet diamond.
//
// Colour is never the only channel: the bands sit at fixed positions, 2 px surface gaps
// split them, the zone bounds are printed under their edges, and the verdict line below
// keeps the plain-German statement with its ✓/⚠ glyph. That secondary encoding is what
// makes the green↔amber pair legal at ΔE 7.9 for deuteranopia (measured, see index.css).

export function ZoneBar({ brief }: { brief: StockBrief }) {
  const geo = zoneGeometry(brief.price, brief.zone_low, brief.zone_high, brief.analyst_target);
  // No honest geometry (collapsed zone, unusable price) → no bar. The verdict text stands alone.
  if (!geo) return null;

  const digits = boundDigits(brief.zone_low, brief.zone_high);

  // aria-hidden, NOT role="img" with a label: the row is a <button>, so any label here is
  // concatenated into its accessible name — a screen reader would read price, zone and
  // verdict twice, once from the bar and once from the text right below it. The bar draws
  // what the verdict line already states in plain German, and the exact bounds live in the
  // detail list behind the tap, so nothing is only-visual.
  return (
    <span className="zonebar" aria-hidden="true">
      <span className="zonebar-track">
        {geo.targetPct !== null && (
          <span className="zonebar-target" style={{ left: `${geo.targetPct}%` }} />
        )}
        {geo.priceOverflow === null ? (
          <span className="zonebar-now" style={{ left: `${geo.pricePct}%` }} />
        ) : (
          <span className={`zonebar-out zonebar-out-${geo.priceOverflow}`} />
        )}
      </span>
      <span className="zonebar-scale">
        <span className="zonebar-bound zonebar-bound-low num">
          {formatBound(brief.zone_low, digits)}
        </span>
        <span className="zonebar-bound zonebar-bound-high num">
          {formatBound(brief.zone_high, digits)}
        </span>
      </span>
    </span>
  );
}
