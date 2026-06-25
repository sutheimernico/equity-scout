import { num } from "../format";

// Inline SVG line chart — primary series (accent, filled) vs benchmark (grey, dashed). No chart
// library: keeps the bundle self-contained. `vector-effect: non-scaling-stroke` keeps line widths
// constant while the SVG scales responsively with preserveAspectRatio="none".
export function EquityChart({
  equity,
  benchmark,
  label,
  benchmarkLabel,
}: {
  equity: [string, number][];
  benchmark: [string, number][];
  label: string;
  benchmarkLabel: string;
}) {
  const W = 760;
  const H = 260;
  const padTop = 10;
  const padBottom = 18;
  const values = [...equity.map((p) => p[1]), ...benchmark.map((p) => p[1])];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const px = (i: number, n: number) => (n <= 1 ? 0 : (i / (n - 1)) * W);
  const py = (v: number) => padTop + (1 - (v - min) / span) * (H - padTop - padBottom);
  const toPath = (data: [string, number][]) =>
    data.map((p, i) => `${i ? "L" : "M"}${px(i, data.length).toFixed(1)},${py(p[1]).toFixed(1)}`).join(" ");

  const areaPath = `${toPath(equity)} L${W},${(H - padBottom).toFixed(1)} L0,${(H - padBottom).toFixed(1)} Z`;
  const gradientId = `eq-grad-${label.replace(/[^a-z0-9]/gi, "")}`;
  const baselineY = min <= 1 && max >= 1 ? py(1) : null;
  const fromYear = equity[0]?.[0].slice(0, 4) ?? "";
  const toYear = equity[equity.length - 1]?.[0].slice(0, 4) ?? "";

  return (
    <div className="eq-chart">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Wertentwicklung">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" className="eq-grad-top" />
            <stop offset="100%" className="eq-grad-bottom" />
          </linearGradient>
        </defs>
        {baselineY !== null && (
          <line x1="0" y1={baselineY} x2={W} y2={baselineY} className="eq-baseline" />
        )}
        <path d={areaPath} fill={`url(#${gradientId})`} stroke="none" />
        <path d={toPath(benchmark)} className="eq-benchmark" fill="none" />
        <path d={toPath(equity)} className="eq-line" fill="none" />
      </svg>
      <div className="eq-meta">
        <div className="eq-legend">
          <span className="eq-key strat">{label}</span>
          <span className="eq-key bench">{benchmarkLabel}</span>
        </div>
        <span className="eq-range tnum">
          {fromYear}–{toYear} · {num(min)}× … {num(max)}× (Start = 1×)
        </span>
      </div>
    </div>
  );
}
