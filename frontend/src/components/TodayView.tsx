import { useEffect, useState } from "react";

import {
  fetchArena,
  fetchEvidence,
  fetchInbox,
  fetchRadar,
  fetchRunHistory,
  type ArenaResponse,
  type EvidenceResponse,
  type InboxResponse,
  type RadarResponse,
  type RunSummary,
} from "../api";
import { pct } from "../format";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { StatTile } from "./StatTile";

// The system-status start page (plan v6 P6): what needs a decision, how the paper depots
// stand, what fired recently, when things last ran. Every block degrades independently —
// a missing data source renders an honest placeholder, never a fake number.
export function TodayView({ onNavigate }: { onNavigate: (view: string) => void }) {
  const [inbox, setInbox] = useState<InboxResponse | null>(null);
  const [arena, setArena] = useState<ArenaResponse | null>(null);
  const [radar, setRadar] = useState<RadarResponse | null>(null);
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [runs, setRuns] = useState<RunSummary[] | null>(null);

  useEffect(() => {
    let ignore = false;
    const guard = <T,>(setter: (v: T) => void) => (v: T) => {
      if (!ignore) setter(v);
    };
    fetchInbox().then(guard(setInbox)).catch(() => undefined);
    fetchArena().then(guard(setArena)).catch(() => undefined);
    fetchRadar().then(guard(setRadar)).catch(() => undefined);
    fetchEvidence().then(guard(setEvidence)).catch(() => undefined);
    fetchRunHistory()
      .then((r) => {
        if (!ignore) setRuns(r.runs);
      })
      .catch(() => undefined);
    return () => {
      ignore = true;
    };
  }, []);

  const openPitches = (inbox?.pitches ?? []).filter((p) => p.status === "open");
  const lanes = arena?.lanes ?? [];
  const inZone = (radar?.watchlist?.entries ?? []).filter((e) => e.in_zone);
  const alerts = (evidence?.recent_alerts ?? []).slice(0, 3);
  const lastRun = runs?.[0];

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Heute</p>
        <h1>Systemstatus auf einen Blick</h1>
        <p className="section-sub">
          Offene Entscheidungen, Depot-Stände, frische Signale und die letzten Läufe — alles
          Paper, alles Recherche, keine Anlageberatung.
        </p>
      </header>

      <div className="kpi-row">
        <StatTile
          label="Offene Pitches"
          value={inbox ? String(openPitches.length) : "—"}
          sub={openPitches.length > 0 ? "warten auf deine Entscheidung" : "nichts offen"}
        />
        <StatTile
          label="Radar in Zone"
          value={radar?.watchlist ? String(inZone.length) : "—"}
          sub={
            inZone.length > 0
              ? inZone.slice(0, 3).map((e) => e.ticker).join(" · ")
              : "kein Titel in der Einstiegszone"
          }
        />
        {lanes.map((lane) => (
          <StatTile
            key={lane.lane}
            label={lane.lane === "nico" ? "Depot Du" : "Depot Autopilot"}
            value={pct(lane.total_return)}
            sub={`vs. Markt ${pct(lane.benchmark_return)}`}
          />
        ))}
      </div>

      <section className="strat-block">
        <h3 className="block-title">Was zuletzt passiert ist</h3>
        {alerts.length === 0 ? (
          <p className="muted">Keine Evidenz-Alarme in letzter Zeit.</p>
        ) : (
          alerts.map((alert, i) => (
            <p className="muted" key={i}>
              <span className="ticker">{alert.ticker}</span> — {alert.reasons?.[0] ?? "Alarm"}{" "}
              <span className="tnum">({String(alert.created_at ?? "").slice(0, 10)})</span>
            </p>
          ))
        )}
        <p className="muted">
          {lastRun
            ? `Letzter Scout-Lauf: ${lastRun.created_at.slice(0, 10)} über ${lastRun.universe_size} Titel.`
            : "Noch kein Scout-Lauf gespeichert."}
        </p>
      </section>

      <section className="strat-block">
        <h3 className="block-title">Direkt weiter</h3>
        <div className="tabbar wrap">
          <button className="tab" onClick={() => onNavigate("inbox")}>
            → Inbox {openPitches.length > 0 ? `(${openPitches.length})` : ""}
          </button>
          <button className="tab" onClick={() => onNavigate("radar")}>
            → Radar
          </button>
          <button className="tab" onClick={() => onNavigate("depots")}>
            → Depots
          </button>
          <button className="tab" onClick={() => onNavigate("learning")}>
            → Lernkurven
          </button>
        </div>
      </section>

      {evidence && <DisclaimerBar text={evidence.disclaimer} />}
    </>
  );
}
