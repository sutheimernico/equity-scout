import type { StockBrief } from "../api";
import {
  ZONE_END_PCT,
  ZONE_START_PCT,
  boundDigits,
  formatBound,
  zoneGeometry,
} from "../zone";

// The entry zone as a meter (2026-08-04 as a three-band bullet bar; rebuilt 2026-08-05
// after "diese Balken sehen nicht schön aus"). ONE marked zone inside a quiet neutral
// track, not three saturated bands: three coloured blocks at 10 px read as the loud
// element of the card when the price marker is the thing that matters. Now the track
// recedes, the zone is a wash, and the needle is the only loud mark.
//
// Colour is never the only channel: the zone sits at a fixed position (always the middle
// third — see zone.ts), the needle's position says which side the price is on, and the
// verdict line right below states it in plain German with a ✓/⚠ glyph. The exact bounds
// live in the detail list, so the printed bound labels are gone — they were a number at
// every card, which is what made the list feel crowded.
//
// Lives in the detail view only; the list carries a compact chip instead.

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
        {/* The zone itself: the only filled area. Accent when the price is inside it,
            muted when it is not — the state is already carried by the needle and the
            verdict, so the fill only has to say "this is the range". */}
        <span
          className={brief.in_zone ? "zonebar-zone in" : "zonebar-zone"}
          style={{ left: `${ZONE_START_PCT}%`, width: `${ZONE_END_PCT - ZONE_START_PCT}%` }}
        />
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
        <span className="zonebar-legend">Einstiegszone</span>
        <span className="zonebar-bound zonebar-bound-high num">
          {formatBound(brief.zone_high, digits)}
        </span>
      </span>
    </span>
  );
}
