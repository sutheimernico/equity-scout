import type { StockChart } from "../api";
import { monthTicks, priceTicks, sparklinePath, yearReturnPct } from "../sparkline";

// One year of closes as an inline SVG from OUR data (nightly scripts/run_insights.py) —
// not the TradingView widget StockChart.tsx embeds on desktop. Three reasons: the service
// worker can cache this so the card still draws with WSL off, it inherits the dark
// cockpit instead of forcing colorTheme "light", and a private cockpit should not load a
// third-party script on every card open.
//
// Axes, not a bare sparkline (Nico 2026-08-05: "bitte mit, dass Du da irgendwie die Monate
// […] und halt auch auf der Y-Achse die Preise"). Design rules applied from the dataviz
// reference:
// - the container includes the x-axis band, so the labels are never cut off by a fixed height
// - grid and axis are solid 1px hairlines one step off the surface, never dashed
// - only the LAST price is direct-labelled; the y-ticks carry the rest (never a number per point)
// - axis and label text wear text tokens; the line alone carries the colour
// - the area fill is a ~10 % wash, not a saturated block

// Plot box in user units. Room on the left for price ticks and below for month labels;
// preserveAspectRatio is "none" for the plot path only, so text keeps its aspect.
const PLOT = { x: 34, y: 6, w: 262, h: 62 };
const VIEW = { w: 300, h: 88 };

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
  const { closes } = chart;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;

  const yOf = (value: number) => PLOT.y + (1 - (value - min) / span) * PLOT.h;
  const xOf = (index: number) => PLOT.x + (index / (closes.length - 1)) * PLOT.w;

  const path = sparklinePath(closes, {
    width: PLOT.w,
    height: PLOT.h,
    pad: 0,
    x: PLOT.x,
    y: PLOT.y,
  });
  // Close the line down to the baseline and back for the wash underneath it.
  const baseline = PLOT.y + PLOT.h;
  const areaPath = `${path} L ${xOf(closes.length - 1)} ${baseline} L ${PLOT.x} ${baseline} Z`;

  const change = yearReturnPct(closes);
  const up = (change ?? 0) >= 0;
  const ticks = priceTicks(min, max, 3);
  const months = monthTicks(chart.dates ?? [], 3);
  const last = closes[closes.length - 1];
  // 1.07 needs decimals, 1915 does not — one rule for ticks and the end label alike.
  const digits = max < 10 ? 2 : max < 100 ? 1 : 0;
  const fmt = (v: number) =>
    v.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });

  return (
    <figure className="yearchart">
      <svg
        viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
        className={up ? "yearchart-svg up" : "yearchart-svg down"}
        // aria-hidden: the caption below states the same fact in text, and the row is a
        // <button> — a labelled graphic here would be folded into its accessible name and
        // read twice (the mistake ZoneBar shipped with on 2026-08-04).
        aria-hidden="true"
      >
        {ticks.map((value) => (
          <g key={value}>
            <line
              className="yc-grid"
              x1={PLOT.x}
              x2={PLOT.x + PLOT.w}
              y1={yOf(value)}
              y2={yOf(value)}
            />
            <text className="yc-tick" x={PLOT.x - 4} y={yOf(value) + 3} textAnchor="end">
              {fmt(value)}
            </text>
          </g>
        ))}
        {/* Baseline under the plot: the anchor the month labels hang from. */}
        <line
          className="yc-axis"
          x1={PLOT.x}
          x2={PLOT.x + PLOT.w}
          y1={PLOT.y + PLOT.h}
          y2={PLOT.y + PLOT.h}
        />
        {months.map((tick) => (
          <text
            key={`${tick.index}-${tick.label}`}
            className="yc-tick"
            x={xOf(tick.index)}
            y={VIEW.h - 4}
            textAnchor="middle"
          >
            {tick.label}
          </text>
        ))}
        <path className="yc-area" d={areaPath} />
        <path className="yc-line" d={path} fill="none" />
        {/* Only the current price gets a marker + label; the ticks carry the rest. */}
        <circle className="yc-now" cx={xOf(closes.length - 1)} cy={yOf(last)} r={3} />
      </svg>
      <figcaption>
        <span className={up ? "brief-good" : "brief-warn"}>
          {change === null
            ? "1 Jahr —"
            : `1 Jahr ${change > 0 ? "+" : change < 0 ? "−" : ""}${Math.abs(change)} %`}
        </span>
        <span className="brief-muted">
          {" "}
          {/* "Stand <Tag>", never "aktuell": this endpoint is the last close in the cached
              series, while the card's price comes from the watchlist run. On 9064.T the two
              differed by 35 JPY (1.880 vs 1.915,50) — two numbers both labelled "aktuell"
              in one card is a contradiction the reader has to resolve. */}
          · Stand {chart.last_date} {fmt(last)}
          {currency ? ` ${currency}` : ""}
        </span>
      </figcaption>
    </figure>
  );
}
