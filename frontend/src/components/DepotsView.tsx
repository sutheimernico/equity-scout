import { useEffect, useState } from "react";

import { fetchPortfolio, type PortfolioState } from "../api";
import { ArenaPanel } from "./ArenaPanel";
import { AutoDepotPanel } from "./AutoDepotPanel";
import { ForwardPanel } from "./ForwardPanel";
import { Portfolio } from "./Portfolio";
import { TimeContextBadge } from "./ui/TimeContextBadge";

type DepotTab = "arena" | "screener" | "forward" | "bots" | "autodepot";

// Every paper depot in ONE place (plan v6 P6) — before this they lived under three
// different names in three different views (Arena, "Demo-Depot" im Screener,
// "Live (Forward)" unter Strategien). Each tab carries its time-context badge.
const TABS: { key: DepotTab; label: string }[] = [
  { key: "arena", label: "Arena (Du vs. Autopilot)" },
  { key: "screener", label: "Screener-Depot" },
  { key: "forward", label: "Strategie-Forward" },
  { key: "bots", label: "ML-Bots" },
  { key: "autodepot", label: "Auto-Depot" },
];

function ScreenerDepot() {
  const [portfolio, setPortfolio] = useState<PortfolioState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    fetchPortfolio()
      .then((p) => {
        if (!ignore) setPortfolio(p);
      })
      .catch((e: unknown) => {
        if (!ignore) setError(String(e));
      });
    return () => {
      ignore = true;
    };
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!portfolio) return <p className="state">Lädt…</p>;
  return <Portfolio data={portfolio} />;
}

export function DepotsView() {
  const [tab, setTab] = useState<DepotTab>("arena");

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Entscheiden · Depots</p>
        <h1>Alle Paper-Depots an einem Ort</h1>
        <p className="section-sub">
          Fünf Demo-Depots, fünf Ansätze — alle mit Spielgeld, keins echt. Das Badge an jedem Tab
          sagt, ob du einen Backtest oder einen vorwärtslaufenden Track ansiehst.
        </p>
      </header>

      <div className="tabbar wrap">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={tab === t.key ? "tab active" : "tab"}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="chip-row" style={{ marginBottom: "var(--space-3)" }}>
        {tab === "arena" && <TimeContextBadge kind="paper" />}
        {tab === "screener" && <TimeContextBadge kind="paper" />}
        {(tab === "forward" || tab === "bots" || tab === "autodepot") && (
          <TimeContextBadge kind="forward" />
        )}
      </div>

      {tab === "arena" && <ArenaPanel embedded />}
      {tab === "screener" && <ScreenerDepot />}
      {tab === "forward" && (
        <ForwardPanel include={(name) => !name.startsWith("ML ")} />
      )}
      {tab === "bots" && (
        <ForwardPanel
          include={(name) => name.startsWith("ML ")}
          emptyHint="Die ML-Bots handeln erst, wenn ihre Modell-Familie einen promoteten Champion hat — kein nachgewiesener Edge, kein Trade. Das nächtliche Training (nightly_train.sh) registriert und promotet Kandidaten."
          botNote
        />
      )}
      {tab === "autodepot" && <AutoDepotPanel />}
    </>
  );
}
