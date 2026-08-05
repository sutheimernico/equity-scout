import { useEffect, useState } from "react";

import { fetchPortfolio, type PortfolioState } from "../api";
import { ArenaPanel } from "./ArenaPanel";
import { AutoDepotPanel } from "./AutoDepotPanel";
import { ForwardPanel } from "./ForwardPanel";
import { KurzfristArenaPanel } from "./KurzfristArenaPanel";
import { OverviewPanel } from "./OverviewPanel";
import { PhoneDepot } from "./PhoneDepot";
import { Portfolio } from "./Portfolio";
import { TimeContextBadge } from "./ui/TimeContextBadge";

type DepotTab = "gesamt" | "arena" | "screener" | "forward" | "bots" | "autodepot" | "shortterm";

// Every paper depot in ONE place (plan v6 P6) — before this they lived under three
// different names in three different views (Arena, "Demo-Depot" im Screener,
// "Live (Forward)" unter Strategien). Each tab carries its time-context badge.
const TABS: { key: DepotTab; label: string }[] = [
  { key: "gesamt", label: "Gesamt" },
  { key: "arena", label: "Arena (Du vs. Autopilot)" },
  { key: "screener", label: "Screener-Depot" },
  { key: "forward", label: "Strategie-Forward" },
  { key: "bots", label: "ML-Bots" },
  { key: "autodepot", label: "Auto-Depot" },
  { key: "shortterm", label: "Kurzfrist-Arena" },
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
  const [tab, setTab] = useState<DepotTab>("gesamt");

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Entscheiden · Depots</p>
        <h1>Alle Paper-Depots an einem Ort</h1>
        <p className="section-sub">
          Gesamtblick plus sechs Demo-Depots — alle mit Spielgeld, keins echt. Das Badge an jedem
          Tab sagt, ob du einen Backtest oder einen vorwärtslaufenden Track ansiehst.
        </p>
      </header>

      {/* Phone: one screen, the two questions ("was hält er, was hat er gehandelt").
          Desktop: the seven-tab detail below. CSS decides which one is visible — both
          render, but they read the same two endpoints either way, so the only cost is one
          extra fetch pair on a phone, not a second data path to keep in step. */}
      <div className="only-phone">
        <PhoneDepot />
      </div>

      <div className="only-desktop">
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
          {tab === "gesamt" && <TimeContextBadge kind="paper" />}
          {tab === "arena" && <TimeContextBadge kind="paper" />}
          {tab === "screener" && <TimeContextBadge kind="paper" />}
          {(tab === "forward" ||
            tab === "bots" ||
            tab === "autodepot" ||
            tab === "shortterm") && <TimeContextBadge kind="forward" />}
        </div>

        {tab === "gesamt" && <OverviewPanel />}
        {tab === "arena" && <ArenaPanel embedded />}
        {tab === "screener" && <ScreenerDepot />}
        {tab === "forward" && <ForwardPanel include={(name) => !name.startsWith("ML ")} />}
        {tab === "bots" && (
          <ForwardPanel
            include={(name) => name.startsWith("ML ")}
            emptyHint="Die ML-Bots handeln erst, wenn ihre Modell-Familie einen promoteten Champion hat — kein nachgewiesener Edge, kein Trade. Das nächtliche Training (nightly_train.sh) registriert und promotet Kandidaten."
            botNote
          />
        )}
        {tab === "autodepot" && <AutoDepotPanel />}
        {tab === "shortterm" && <KurzfristArenaPanel />}
      </div>
    </>
  );
}
