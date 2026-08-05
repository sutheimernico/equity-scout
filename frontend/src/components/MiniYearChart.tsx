import type { StockChart } from "../api";
import { sparklinePath, yearReturnPct } from "../sparkline";

// One year of closes as an inline SVG from OUR data (nightly scripts/run_insights.py) —
// not the TradingView widget StockChart.tsx embeds on desktop. Three reasons: the service
// worker can cache this so the card still draws with WSL off, it inherits the dark
// cockpit instead of forcing colorTheme "light", and a private cockpit should not load a
// third-party script on every card open.
const BOX = { width: 300, height: 64, pad: 3 } as const;

export function MiniYearChart({
  chart,
  currency,
}: {
  chart: StockChart | null;
  currency: string | null;
}) {
  if (!chart || chart.closes.length < 2) {
    return <p className="brief-muted">Kein Kursverlauf gespeichert.</p>;
  }
  const path = sparklinePath(chart.closes, BOX);
  const change = yearReturnPct(chart.closes);
  const up = (change ?? 0) >= 0;
  const label =
    change === null
      ? "1 Jahr — kein Vergleichswert"
      : `1 Jahr ${change > 0 ? "+" : change < 0 ? "−" : ""}${Math.abs(change)} %`;

  return (
    <figure className="yearchart">
      <svg
        viewBox={`0 0 ${BOX.width} ${BOX.height}`}
        // Width comes from CSS; the box is a coordinate system, not a pixel size.
        preserveAspectRatio="none"
        className={up ? "yearchart-svg up" : "yearchart-svg down"}
        // aria-hidden because the caption below states the same fact as text. Without it a
        // screen reader inside the row's <button> would read the shape's label and the
        // caption twice (the mistake ZoneBar shipped with and fixed on 2026-08-04).
        aria-hidden="true"
      >
        <path d={path} fill="none" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className={up ? "brief-good" : "brief-warn"}>
        {label}
        <span className="brief-muted">
          {" "}
          · {chart.first_date} → {chart.last_date}
          {currency ? ` · ${currency}` : ""}
        </span>
      </figcaption>
    </figure>
  );
}
