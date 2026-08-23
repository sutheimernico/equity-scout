import { useEffect, useState } from "react";

import { fetchPortfolio, type PortfolioState } from "../api";
import { FunnelView } from "./FunnelView";
import { ForwardPanel } from "./ForwardPanel";
import { LearningCurvePanel } from "./LearningCurvePanel";
import { MLSection } from "./MLSection";
import { ModelPanel } from "./ModelPanel";
import { Portfolio } from "./Portfolio";
import { RadarPanel } from "./RadarPanel";
import { RefreshPanel } from "./RefreshPanel";
import { StrategyDashboard } from "./StrategyDashboard";

type LaborTab =
  | "aktualisieren"
  | "strategien"
  | "modell"
  | "filter"
  | "lernkurven"
  | "screener"
  | "radar"
  | "depots";

// "Mehr → Labor" (mockup v2): the research surfaces in ONE place — the models keep
// running unchanged in the background; these tabs are the windows onto them. Nothing
// was deleted in the rebuild: the raw Screener and Radar views and the research paper
// depots (Screener-Depot, Strategie-Forward, ML-Bots) moved here from the old nav.
const TABS: { key: LaborTab; label: string }[] = [
  // First: the one tab you come here to DO something in, not to read.
  { key: "aktualisieren", label: "Aktualisieren" },
  { key: "strategien", label: "Strategien" },
  { key: "modell", label: "Entry-Modell" },
  { key: "filter", label: "Signal-Filter" },
  { key: "lernkurven", label: "Lernkurven" },
  { key: "screener", label: "Screener (Rohdaten)" },
  { key: "radar", label: "Radar (Rohdaten)" },
  { key: "depots", label: "Forschungs-Depots" },
];

function ResearchDepots() {
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

  return (
    <>
      <h2 className="section-title">Strategie-Forward</h2>
      <ForwardPanel include={(name) => !name.startsWith("ML ")} />
      <h2 className="section-title">ML-Bots</h2>
      <ForwardPanel
        include={(name) => name.startsWith("ML ")}
        emptyHint="Die ML-Bots handeln erst, wenn ihre Modell-Familie einen promoteten Champion hat — kein nachgewiesener Edge, kein Trade. Das nächtliche Training (nightly_train.sh) registriert und promotet Kandidaten."
        botNote
      />
      <h2 className="section-title">Screener-Depot</h2>
      {error && <p className="state err">Fehler: {error}</p>}
      {!error && !portfolio && <p className="state">Lädt…</p>}
      {portfolio && <Portfolio data={portfolio} />}
    </>
  );
}

export function LaborView() {
  const [tab, setTab] = useState<LaborTab>("strategien");

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Mehr · Labor</p>
        <h1>Die Forschung hinter den Vorschlägen</h1>
        <p className="section-sub">
          Für Neugierige: Strategien, Modelle, Lernkurven und die Roh-Sichten des Screeners.
          Nichts hiervon brauchst du täglich — die Modelle laufen auch ohne Zuschauer.
        </p>
      </header>

      {/* Eight tabs: sideways on the phone (see .tabbar.scroll), wrapping on desktop
          where the row has the width for it. */}
      <div className="tabbar wrap scroll">
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

      {tab === "aktualisieren" && <RefreshPanel />}
      {tab === "strategien" && <StrategyDashboard />}
      {tab === "modell" && <ModelPanel />}
      {tab === "filter" && <MLSection />}
      {tab === "lernkurven" && <LearningCurvePanel />}
      {tab === "screener" && <FunnelView />}
      {tab === "radar" && <RadarPanel />}
      {tab === "depots" && <ResearchDepots />}
    </>
  );
}
