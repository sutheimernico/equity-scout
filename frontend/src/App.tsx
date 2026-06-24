import { useEffect, useMemo, useState } from "react";

import { fetchLatestRun, fetchRunHistory, type LatestRun, type RunSummary } from "./api";
import { MethodologyNote } from "./components/MethodologyNote";
import { PickCard } from "./components/PickCard";
import { RunHistory } from "./components/RunHistory";
import { StatTile } from "./components/StatTile";
import { BUCKET_LABELS } from "./format";

const BUCKET_ORDER = ["defensive", "balanced", "aggressive"];

export default function App() {
  const [run, setRun] = useState<LatestRun | null>(null);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [bucket, setBucket] = useState("defensive");
  const [region, setRegion] = useState("all");

  useEffect(() => {
    fetchLatestRun().then(setRun).catch((e: unknown) => setError(String(e)));
    fetchRunHistory().then((h) => setHistory(h.runs)).catch(() => undefined);
  }, []);

  const picks = run?.buckets[bucket] ?? [];
  // Regions present in the active bucket, for the filter dropdown.
  const regions = useMemo(
    () => ["all", ...Array.from(new Set(picks.map((p) => p.instrument.region))).sort()],
    [picks],
  );
  const visiblePicks =
    region === "all" ? picks : picks.filter((p) => p.instrument.region === region);

  if (error) return <main className="content state err">Error: {error}</main>;
  if (!run) return <main className="content state">Loading…</main>;

  const gate = run.gate_stats ?? { total_gated: 0, by_region: {}, by_reason: {} };
  const passed = (run.universe_size ?? 0) - gate.total_gated;
  const availableBuckets = BUCKET_ORDER.filter((b) => run.buckets[b]);

  return (
    <>
      <header className="topbar">
        <span className="brand">
          equity-scout<span className="dot">.</span>
        </span>
        <span className="meta">{run.created_at ?? "no runs yet"}</span>
      </header>

      <main className="content">
        <div className="kpi-row">
          <StatTile label="Universe" value={String(run.universe_size ?? 0)} sub="instruments screened" />
          <StatTile label="Passed gate" value={String(passed)} sub="enough data to rank" />
          <StatTile label="Gated out" value={String(gate.total_gated)} sub="thin / invalid data" />
          <StatTile label="Buckets" value={String(availableBuckets.length)} sub="risk profiles" />
        </div>

        <MethodologyNote />

        <div className="tabbar">
          {availableBuckets.map((b) => (
            <button
              key={b}
              className={b === bucket ? "tab active" : "tab"}
              onClick={() => {
                setBucket(b);
                setRegion("all");
              }}
            >
              {BUCKET_LABELS[b] ?? b}
            </button>
          ))}
          <div className="filter">
            <select className="region" value={region} onChange={(e) => setRegion(e.target.value)}>
              {regions.map((r) => (
                <option key={r} value={r}>
                  {r === "all" ? "All regions" : r}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="cards">
          {visiblePicks.map((p) => (
            <PickCard
              key={p.instrument.ticker}
              pick={p}
              weights={run.bucket_weights[bucket] ?? {}}
            />
          ))}
          {visiblePicks.length === 0 && <p className="muted">No picks for this filter.</p>}
        </div>

        <h2 className="section-title">Recent runs</h2>
        <RunHistory runs={history} />

        <footer>{run.disclaimer}</footer>
      </main>
    </>
  );
}
