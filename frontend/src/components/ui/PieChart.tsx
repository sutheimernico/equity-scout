import { useState } from "react";

// Inline SVG pie with a hover legend — no chart library. Hovering a slice (or its legend row)
// highlights it and shows a one-line quick-info below. `fmt` formats the share (default percent).
export interface PieSlice {
  label: string;
  value: number;
  info?: string; // quick-info shown on hover
}

const sliceColor = (i: number) => `hsl(${(255 + i * 47) % 360} 58% 62%)`;

function polar(cx: number, cy: number, r: number, angleDeg: number) {
  const a = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
}

function arc(cx: number, cy: number, r: number, start: number, end: number) {
  // a single slice as nearly a full circle would degenerate; nudge the sweep just under 360°
  const e = polar(cx, cy, r, Math.min(end, start + 359.99));
  const s = polar(cx, cy, r, start);
  const large = end - start > 180 ? 1 : 0;
  return `M ${cx} ${cy} L ${s.x.toFixed(2)} ${s.y.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${e.x.toFixed(2)} ${e.y.toFixed(2)} Z`;
}

export function PieChart({ slices, fmt }: { slices: PieSlice[]; fmt?: (share: number) => string }) {
  const [active, setActive] = useState<number | null>(null);
  const data = slices.filter((s) => s.value > 0);
  const total = data.reduce((sum, s) => sum + s.value, 0) || 1;
  const share = (v: number) => (fmt ? fmt(v / total) : `${Math.round((v / total) * 100)} %`);

  let angle = 0;
  const arcs = data.map((s, i) => {
    const start = angle;
    angle += (s.value / total) * 360;
    return { ...s, i, path: arc(100, 100, 94, start, angle) };
  });

  if (arcs.length === 0) return <p className="muted">Keine Allokation vorhanden.</p>;

  return (
    <div className="pie">
      <svg viewBox="0 0 200 200" className="pie-svg" role="img" aria-label="Allokation">
        {arcs.map((a) => (
          <path
            key={a.i}
            d={a.path}
            fill={sliceColor(a.i)}
            stroke="var(--bg-surface)"
            strokeWidth="1.5"
            opacity={active === null || active === a.i ? 1 : 0.3}
            onMouseEnter={() => setActive(a.i)}
            onMouseLeave={() => setActive(null)}
          />
        ))}
      </svg>
      <ul className="pie-legend">
        {arcs.map((a) => (
          <li
            key={a.i}
            className={active === a.i ? "pie-legend-item active" : "pie-legend-item"}
            onMouseEnter={() => setActive(a.i)}
            onMouseLeave={() => setActive(null)}
          >
            <span className="pie-dot" style={{ background: sliceColor(a.i) }} />
            <span className="pie-label">{a.label}</span>
            <span className="pie-val tnum">{share(a.value)}</span>
          </li>
        ))}
      </ul>
      <div className="pie-info">
        {active !== null && arcs[active]
          ? `${arcs[active].label} · ${share(arcs[active].value)}${arcs[active].info ? ` · ${arcs[active].info}` : ""}`
          : "Über ein Segment hovern für Details"}
      </div>
    </div>
  );
}
