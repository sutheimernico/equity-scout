import { useState } from "react";

import { FunnelView } from "./components/FunnelView";
import { StrategyDashboard } from "./components/StrategyDashboard";

type View = "strategies" | "funnel";

export default function App() {
  const [view, setView] = useState<View>("strategies");

  return (
    <>
      <header className="topbar">
        <span className="brand">
          equity-scout<span className="dot">.</span>
        </span>
        <nav className="nav">
          <button
            className={view === "strategies" ? "nav-link active" : "nav-link"}
            onClick={() => setView("strategies")}
          >
            Strategien
          </button>
          <button
            className={view === "funnel" ? "nav-link active" : "nav-link"}
            onClick={() => setView("funnel")}
          >
            Aktien-Screener
          </button>
        </nav>
      </header>

      <main className="content">
        {view === "strategies" ? <StrategyDashboard /> : <FunnelView />}
      </main>
    </>
  );
}
