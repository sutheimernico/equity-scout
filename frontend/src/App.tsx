import { useState } from "react";

import { ChatPanel } from "./components/ChatPanel";
import { FunnelView } from "./components/FunnelView";
import { MLSection } from "./components/MLSection";
import { StrategyDashboard } from "./components/StrategyDashboard";

type View = "strategies" | "ml" | "funnel" | "chat";

const NAV: { key: View; label: string }[] = [
  { key: "strategies", label: "Strategien" },
  { key: "ml", label: "Machine Learning" },
  { key: "funnel", label: "Aktien-Screener" },
  { key: "chat", label: "Assistent" },
];

export default function App() {
  const [view, setView] = useState<View>("strategies");

  return (
    <>
      <header className="topbar">
        <span className="brand">
          equity-scout<span className="dot">.</span>
        </span>
        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.key}
              className={view === item.key ? "nav-link active" : "nav-link"}
              onClick={() => setView(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="content">
        {view === "strategies" && <StrategyDashboard />}
        {view === "ml" && <MLSection />}
        {view === "funnel" && <FunnelView />}
        {view === "chat" && <ChatPanel />}
      </main>
    </>
  );
}
