import { useEffect, useMemo, useState } from "react";

import {
  fetchLatestRun,
  fetchRunHistory,
  type LatestRun,
  type RunSummary,
} from "../api";
import { BUCKET_LABELS, pctAbs } from "../format";
import { GatedOutList } from "./GatedOutList";
import { MethodologyNote } from "./MethodologyNote";
import { PickCard } from "./PickCard";
import { RunHistory } from "./RunHistory";
import { StatTile } from "./StatTile";

const BUCKET_ORDER = ["defensive", "balanced", "aggressive"];

// The original stock factor-funnel view, extracted from App so the shell can switch top-level views.
export function FunnelView() {
  const [run, setRun] = useState<LatestRun | null>(null);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [bucket, setBucket] = useState("defensive");
  const [region, setRegion] = useState("all");
  const [sector, setSector] = useState("all");

  useEffect(() => {
    fetchLatestRun().then(setRun).catch((e: unknown) => setError(String(e)));
    fetchRunHistory().then((h) => setHistory(h.runs)).catch(() => undefined);
  }, []);

  const picks = run?.buckets[bucket] ?? [];
  const regions = useMemo(
    () => ["all", ...Array.from(new Set(picks.map((p) => p.instrument.region))).sort()],
    [picks],
  );
  const sectors = useMemo(
    () => ["all", ...Array.from(new Set(picks.map((p) => p.instrument.sector))).sort()],
    [picks],
  );
  const visiblePicks = picks.filter(
    (p) =>
      (region === "all" || p.instrument.region === region) &&
      (sector === "all" || p.instrument.sector === sector),
  );

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!run) return <p className="state">Lädt…</p>;

  const gate = run.gate_stats ?? { total_gated: 0, by_region: {}, by_reason: {} };
  const passed = (run.universe_size ?? 0) - gate.total_gated;
  const availableBuckets = BUCKET_ORDER.filter((b) => run.buckets[b]);
  const dataQuality = run.data_quality;

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Signale · Screener</p>
        <h1>Globaler Faktor-Funnel</h1>
        <p className="section-sub">
          Ein regelbasierter Screen über ein globales Aktienuniversum — fünf Faktor-Gruppen, sortiert in
          Risiko-Buckets. <strong>Kein KI-Modell</strong>, keine Anlageberatung. Das zugehörige
          Paper-Depot liegt unter <strong>Entscheiden → Depots → Screener-Depot</strong>.
        </p>
      </header>

      <div className="kpi-row reveal">
        <StatTile label="Universum" value={String(run.universe_size ?? 0)} sub="Aktien gescreent" />
        <StatTile label="Daten ok" value={String(passed)} sub="genug Daten zum Ranken" />
        <StatTile label="Aussortiert" value={String(gate.total_gated)} sub="zu dünne/ungültige Daten" />
        <StatTile label="Buckets" value={String(availableBuckets.length)} sub="Risiko-Profile" />
        {!!dataQuality?.attempted && (
          <StatTile
            label="Fetch-Fehlerquote"
            value={pctAbs(dataQuality.fetch_error_rate)}
            sub={`${dataQuality.info_failed + dataQuality.closes_failed} von ${dataQuality.attempted} Abrufen`}
          />
        )}
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
              setSector("all");
            }}
          >
            {BUCKET_LABELS[b] ?? b}
          </button>
        ))}
        <div className="filter">
          <select className="region" value={region} onChange={(e) => setRegion(e.target.value)}>
            {regions.map((r) => (
              <option key={r} value={r}>
                {r === "all" ? "Alle Regionen" : r}
              </option>
            ))}
          </select>
          <select className="region" value={sector} onChange={(e) => setSector(e.target.value)}>
            {sectors.map((s) => (
              <option key={s} value={s}>
                {s === "all" ? "Alle Sektoren" : s}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="cards reveal">
        {visiblePicks.map((p) => (
          <PickCard key={p.instrument.ticker} pick={p} weights={run.bucket_weights[bucket] ?? {}} />
        ))}
        {visiblePicks.length === 0 && <p className="muted">Keine Picks für diesen Filter.</p>}
      </div>

      <GatedOutList gatedOut={run.gated_out ?? {}} byRegion={gate.by_region} />

      <h2 className="section-title">Letzte Läufe</h2>
      <RunHistory runs={history} />

      <footer>{run.disclaimer}</footer>
    </>
  );
}
