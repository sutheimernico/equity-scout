import { useEffect, useMemo, useState } from "react";

import {
  fetchFilterOptions,
  fetchLatestRun,
  fetchRunHistory,
  type FilterOptions,
  type LatestFilters,
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

// German labels for the coarse server-side region groups (see api /api/filters).
const REGION_GROUP_LABELS: Record<string, string> = {
  europe: "Europa",
  americas: "Amerika",
  asia: "Asien",
  oceania: "Ozeanien",
};

// The original stock factor-funnel view, extracted from App so the shell can switch top-level views.
export function FunnelView() {
  const [run, setRun] = useState<LatestRun | null>(null);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bucket, setBucket] = useState("defensive");
  const [region, setRegion] = useState("all");
  const [country, setCountry] = useState("all");
  const [sector, setSector] = useState("all");

  // Filters run SERVER-SIDE over the run's full persisted ranking (~6k names), not just
  // the stored top picks — "Energie + Japan" needs the whole cross-section to be useful.
  const filters = useMemo<LatestFilters>(
    () => ({
      ...(region !== "all" ? { region } : {}),
      ...(country !== "all" ? { country } : {}),
      ...(sector !== "all" ? { sector } : {}),
    }),
    [region, country, sector],
  );
  const filterActive = Object.keys(filters).length > 0;

  useEffect(() => {
    fetchLatestRun(filters).then(setRun).catch((e: unknown) => setError(String(e)));
  }, [filters]);
  useEffect(() => {
    fetchRunHistory().then((h) => setHistory(h.runs)).catch(() => undefined);
    fetchFilterOptions().then(setOptions).catch(() => undefined);
  }, []);

  const visiblePicks = run?.buckets[bucket] ?? [];

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
            onClick={() => setBucket(b)}
          >
            {BUCKET_LABELS[b] ?? b}
          </button>
        ))}
        <div className="filter">
          <select className="region" value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="all">Alle Regionen</option>
            {(options?.region_groups ?? []).map((g) => (
              <option key={g} value={g}>
                {REGION_GROUP_LABELS[g] ?? g}
              </option>
            ))}
          </select>
          <select className="region" value={country} onChange={(e) => setCountry(e.target.value)}>
            <option value="all">Alle Länder</option>
            {(options?.countries ?? []).map((c) => (
              <option key={c.value} value={c.value}>
                {c.value} ({c.count})
              </option>
            ))}
          </select>
          <select className="region" value={sector} onChange={(e) => setSector(e.target.value)}>
            <option value="all">Alle Sektoren</option>
            {(options?.sectors ?? []).map((s) => (
              <option key={s.value} value={s.value}>
                {s.value} ({s.count})
              </option>
            ))}
          </select>
          {filterActive && (
            <button
              className="tab"
              onClick={() => {
                setRegion("all");
                setCountry("all");
                setSector("all");
              }}
            >
              Filter zurücksetzen
            </button>
          )}
        </div>
      </div>

      {filterActive && run.filter_unavailable && (
        <p className="muted">
          Für den letzten Lauf ist noch kein vollständiges Ranking gespeichert — Filter stehen ab
          dem nächsten Screener-Lauf zur Verfügung.
        </p>
      )}
      {filterActive && run.filter_matches !== undefined && (
        <p className="muted">
          {run.filter_matches} Treffer im gesamten Ranking — Top {Math.min(10, visiblePicks.length)}{" "}
          je Bucket angezeigt. Hinweis: US-gelistete ADRs zählen als USA (Listing-Land).
        </p>
      )}

      <div className="cards reveal">
        {visiblePicks.map((p) => (
          <PickCard key={p.instrument.ticker} pick={p} weights={run.bucket_weights[bucket] ?? {}} />
        ))}
        {visiblePicks.length === 0 && <p className="muted">Keine Treffer für diesen Filter.</p>}
      </div>

      <GatedOutList gatedOut={run.gated_out ?? {}} byRegion={gate.by_region} />

      <h2 className="section-title">Letzte Läufe</h2>
      <RunHistory runs={history} />

      <footer>{run.disclaimer}</footer>
    </>
  );
}
