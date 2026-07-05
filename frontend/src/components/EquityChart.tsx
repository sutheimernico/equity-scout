import { num } from "../format";

// One overlaid line in multi-series mode. `color` is a CSS-var string, e.g. "var(--accent)".
export interface ChartSeries {
  label: string;
  points: [string, number][];
  color: string;
  dashed?: boolean;
}

// Inline SVG line chart — no chart library, keeps the bundle self-contained. Two modes:
//   • single-series (default): filled primary line (accent) + dashed benchmark (grey) from the
//     equity/benchmark props. This is the original API — existing callers are unchanged.
//   • multi-series: pass `series` to overlay N named lines, each with its own token color; when
//     present it supersedes equity/benchmark/label/benchmarkLabel. Used by the Arena race.
// `vector-effect: non-scaling-stroke` keeps line widths constant under preserveAspectRatio="none".
export function EquityChart({
  equity,
  benchmark,
  label,
  benchmarkLabel,
  series,
  ariaLabel,
}: {
  equity?: [string, number][];
  benchmark?: [string, number][];
  label?: string;
  benchmarkLabel?: string;
  series?: ChartSeries[];
  ariaLabel?: string;
}) {
  const W = 760;
  const H = 260;
  const padTop = 10;
  const padBottom = 18;

  const multi = series !== undefined;
  // Normalize both modes to a list of point-series for the shared min/max + range math.
  const allSeries: ChartSeries[] = multi
    ? series
    : [
        { label: benchmarkLabel ?? "", points: benchmark ?? [], color: "var(--text-muted)", dashed: true },
        { label: label ?? "", points: equity ?? [], color: "var(--accent)" },
      ];

  const values = allSeries.flatMap((s) => s.points.map((p) => p[1]));
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const span = max - min || 1;

  const px = (i: number, n: number) => (n <= 1 ? 0 : (i / (n - 1)) * W);
  const py = (v: number) => padTop + (1 - (v - min) / span) * (H - padTop - padBottom);
  const toPath = (data: [string, number][]) =>
    data.map((p, i) => `${i ? "L" : "M"}${px(i, data.length).toFixed(1)},${py(p[1]).toFixed(1)}`).join(" ");

  const baselineY = min <= 1 && max >= 1 ? py(1) : null;

  // Year range: single mode reads the primary curve; multi mode the longest series (all share dates).
  const eq = equity ?? [];
  const rangeSource = multi
    ? allSeries.reduce((best, s) => (s.points.length > best.length ? s.points : best), [] as [string, number][])
    : eq;
  const fromYear = rangeSource[0]?.[0].slice(0, 4) ?? "";
  const toYear = rangeSource[rangeSource.length - 1]?.[0].slice(0, 4) ?? "";

  // Single-mode gradient area under the primary (equity) line.
  const areaPath = `${toPath(eq)} L${W},${(H - padBottom).toFixed(1)} L0,${(H - padBottom).toFixed(1)} Z`;
  const gradientId = `eq-grad-${(label ?? "").replace(/[^a-z0-9]/gi, "")}`;

  return (
    <div className="eq-chart">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={ariaLabel ?? "Wertentwicklung"}>
        {!multi && (
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" className="eq-grad-top" />
              <stop offset="100%" className="eq-grad-bottom" />
            </linearGradient>
          </defs>
        )}
        {baselineY !== null && <line x1="0" y1={baselineY} x2={W} y2={baselineY} className="eq-baseline" />}
        {!multi ? (
          <>
            <path d={areaPath} fill={`url(#${gradientId})`} stroke="none" />
            <path d={toPath(benchmark ?? [])} className="eq-benchmark" fill="none" />
            <path d={toPath(eq)} className="eq-line" fill="none" />
          </>
        ) : (
          allSeries.map((s) => (
            <path
              key={s.label}
              d={toPath(s.points)}
              className={s.dashed ? "eq-series dashed" : "eq-series"}
              style={{ stroke: s.color }}
              fill="none"
            />
          ))
        )}
      </svg>
      <div className="eq-meta">
        {!multi ? (
          <div className="eq-legend">
            <span className="eq-key strat">{label}</span>
            <span className="eq-key bench">{benchmarkLabel}</span>
          </div>
        ) : (
          <div className="eq-legend">
            {allSeries.map((s) => (
              <span className="eq-legend-item" key={s.label}>
                {/* swatch color + line style come from the series token (set inline) */}
                <span className="eq-swatch" style={{ borderTopColor: s.color, borderTopStyle: s.dashed ? "dashed" : "solid" }} />
                {s.label}
              </span>
            ))}
          </div>
        )}
        <span className="eq-range tnum">
          {fromYear}–{toYear} · {num(min)}× … {num(max)}× (Start = 1×)
        </span>
      </div>
    </div>
  );
}
