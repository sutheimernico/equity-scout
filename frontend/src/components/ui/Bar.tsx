// Reusable progress / comparison bar. Optional reference marker (a tick at `at` ∈ [0,1])
// sits in the relative wrapper, outside the clipped track, so it stays visible.
export function Bar({
  value,
  max = 1,
  tone,
  marker,
}: {
  value: number;
  max?: number;
  tone?: "accent" | "cost" | "neg";
  marker?: { at: number; label?: string };
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const fillClass = tone === "cost" ? "bar-fill cost" : tone === "neg" ? "bar-fill neg" : "bar-fill";
  const markerLeft = marker ? Math.max(0, Math.min(100, marker.at * 100)) : 0;
  return (
    <div className="bar">
      <div className="bar-track">
        <div className={fillClass} style={{ width: `${pct}%` }} />
      </div>
      {marker && (
        <span className="bar-marker" style={{ left: `${markerLeft}%` }}>
          {marker.label && <span className="bar-marker-label">{marker.label}</span>}
        </span>
      )}
    </div>
  );
}
