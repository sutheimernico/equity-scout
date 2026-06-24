import { useEffect, useMemo, useState } from "react";

import { fetchHistory, fetchLatest, type Latest, type RunSummary } from "./api";
import { PickCard } from "./components/PickCard";

const BUCKET_ORDER = ["defensive", "balanced", "aggressive"];

export default function App() {
  const [latest, setLatest] = useState<Latest | null>(null);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState("defensive");
  const [region, setRegion] = useState("all");

  useEffect(() => {
    fetchLatest().then(setLatest).catch((e: unknown) => setError(String(e)));
    fetchHistory().then((h) => setHistory(h.runs)).catch(() => undefined);
  }, []);

  const picks = latest?.buckets[tab] ?? [];
  // Regions present in the active bucket, for the filter dropdown (recomputed only when picks change).
  const regions = useMemo(
    () => ["all", ...Array.from(new Set(picks.map((p) => p.instrument.region))).sort()],
    [picks],
  );
  const visible = region === "all" ? picks : picks.filter((p) => p.instrument.region === region);

  if (error) {
    return (
      <main className="wrap">
        <p className="err">Error: {error}</p>
      </main>
    );
  }
  if (!latest) {
    return (
      <main className="wrap">
        <p>Loading…</p>
      </main>
    );
  }

  const gs = latest.gate_stats ?? { total_gated: 0, by_region: {}, by_reason: {} };
  const byRegion = Object.entries(gs.by_region ?? {});

  return (
    <main className="wrap">
      <h1>
        equity-scout <small>{latest.created_at ?? "(no runs yet)"}</small>
      </h1>
      <p className="stats">
        Universe {latest.universe_size ?? 0} · gated out {gs.total_gated}
        {byRegion.length > 0 && (
          <> · gated by region: {byRegion.map(([r, n]) => `${r} ${n}`).join(", ")}</>
        )}
      </p>

      <div className="tabs">
        {BUCKET_ORDER.filter((b) => latest.buckets[b]).map((b) => (
          <button
            key={b}
            className={b === tab ? "tab active" : "tab"}
            onClick={() => {
              setTab(b);
              setRegion("all");
            }}
          >
            {b}
          </button>
        ))}
        <select className="region" value={region} onChange={(e) => setRegion(e.target.value)}>
          {regions.map((r) => (
            <option key={r} value={r}>
              {r === "all" ? "all regions" : r}
            </option>
          ))}
        </select>
      </div>

      <div className="picks">
        {visible.map((p) => (
          <PickCard key={p.instrument.ticker} pick={p} />
        ))}
        {visible.length === 0 && <p className="muted">No picks for this filter.</p>}
      </div>

      <h2 className="section">Recent runs</h2>
      <div className="history">
        {history.map((run, i) => (
          <div key={i} className="hist-row">
            {run.created_at} — universe {run.universe_size}, gated {run.total_gated} —{" "}
            {Object.entries(run.picks)
              .map(([b, ts]) => `${b} ${ts.length}`)
              .join(" · ")}
          </div>
        ))}
        {history.length === 0 && <p className="muted">No history yet.</p>}
      </div>

      <footer>{latest.disclaimer}</footer>
    </main>
  );
}
