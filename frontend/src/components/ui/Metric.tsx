import { Bar } from "./Bar";

// A reference anchor turns a naked number into one you can judge at a glance:
// the bar fills to the value, a tick marks the comparison point, the caption names it.
export interface MetricReference {
  fillValue: number; // [0,1] — how full the bar is for the metric value
  markerAt: number; // [0,1] — where the comparison tick sits
  caption: string; // e.g. "Zufall 50 %", "60/40 ≈ 0.60", "SPY −55 %"
  tone?: "accent" | "neg";
}

export function Metric({
  label,
  value,
  help,
  reference,
}: {
  label: string;
  value: string;
  help?: string;
  reference?: MetricReference;
}) {
  return (
    <div className={reference ? "metric metric--wide" : "metric"} title={help}>
      <div className="metric-label">{label}</div>
      <div className="metric-value tnum">{value}</div>
      {reference && (
        <div className="metric-ref">
          <Bar value={reference.fillValue} max={1} tone={reference.tone} marker={{ at: reference.markerAt }} />
          <div className="metric-ref-caption">{reference.caption}</div>
        </div>
      )}
    </div>
  );
}
