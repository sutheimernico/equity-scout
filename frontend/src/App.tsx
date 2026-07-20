import { Fragment, useEffect, useState } from "react";

import { ChatPanel } from "./components/ChatPanel";
import { DepotsView } from "./components/DepotsView";
import { ProofView } from "./components/ProofView";
import { FunnelView } from "./components/FunnelView";
import { InboxPanel } from "./components/InboxPanel";
import { LearningCurvePanel } from "./components/LearningCurvePanel";
import { MLSection } from "./components/MLSection";
import { ModelPanel } from "./components/ModelPanel";
import { RadarPanel } from "./components/RadarPanel";
import { StrategyDashboard } from "./components/StrategyDashboard";
import { TodayView } from "./components/TodayView";
import { VoicesPanel } from "./components/VoicesPanel";

type View =
  | "today"
  | "funnel"
  | "radar"
  | "voices"
  | "inbox"
  | "depots"
  | "proof"
  | "strategies"
  | "model"
  | "ml"
  | "learning"
  | "chat";

// v6 IA (plan P6): visible group labels instead of an anonymous hairline, a "Heute" start
// page, all paper depots under ONE nav item, and unambiguous German names — "Entry-Modell"
// vs "Signal-Filter" ends the old Modell/Meta-Modell collision.
type Group = "start" | "signale" | "entscheiden" | "forschung" | "mehr";

const GROUP_LABELS: Record<Group, string> = {
  start: "",
  signale: "Signale",
  entscheiden: "Entscheiden",
  forschung: "Forschung",
  mehr: "",
};

const NAV: { key: View; label: string; group: Group }[] = [
  { key: "today", label: "Heute", group: "start" },
  { key: "funnel", label: "Screener", group: "signale" },
  { key: "radar", label: "Radar", group: "signale" },
  { key: "voices", label: "Stimmen", group: "signale" },
  { key: "inbox", label: "Inbox", group: "entscheiden" },
  { key: "depots", label: "Depots", group: "entscheiden" },
  { key: "proof", label: "Beweis", group: "entscheiden" },
  { key: "strategies", label: "Strategien", group: "forschung" },
  { key: "model", label: "Entry-Modell", group: "forschung" },
  { key: "ml", label: "Signal-Filter", group: "forschung" },
  { key: "learning", label: "Lernkurven", group: "forschung" },
  { key: "chat", label: "Assistent", group: "mehr" },
];

// Reveal-on-scroll: one global observer fades in any `.reveal` element as it enters the viewport.
// A MutationObserver picks up async-loaded and tab-switched sections without per-component wiring.
function useRevealOnScroll() {
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" },
    );
    let scheduled = false;
    const scan = () => {
      scheduled = false;
      document.querySelectorAll<HTMLElement>(".reveal:not(.in)").forEach((el) => {
        if (reduce) el.classList.add("in");
        else io.observe(el);
      });
    };
    scan();
    const mo = new MutationObserver(() => {
      if (!scheduled) {
        scheduled = true;
        requestAnimationFrame(scan);
      }
    });
    mo.observe(document.body, { childList: true, subtree: true });
    return () => {
      io.disconnect();
      mo.disconnect();
    };
  }, []);
}

export default function App() {
  const [view, setView] = useState<View>("today");
  useRevealOnScroll();

  return (
    <>
      <div className="aurora" aria-hidden="true" />
      <div className="shell">
        <aside className="sidebar">
          <span className="brand">
            equity-scout<span className="dot">.</span>
          </span>
          <nav className="nav">
            {NAV.map((item, i) => (
              <Fragment key={item.key}>
                {i > 0 && NAV[i - 1].group !== item.group && (
                  <>
                    <span className="nav-sep" aria-hidden="true" />
                    {GROUP_LABELS[item.group] && (
                      <span className="nav-group-label">{GROUP_LABELS[item.group]}</span>
                    )}
                  </>
                )}
                <button
                  className={view === item.key ? "nav-link active" : "nav-link"}
                  onClick={() => setView(item.key)}
                >
                  {item.label}
                </button>
              </Fragment>
            ))}
          </nav>
        </aside>

        <main className="content">
          <div className="view" key={view}>
            {view === "today" && <TodayView onNavigate={(v) => setView(v as View)} />}
            {view === "funnel" && <FunnelView />}
            {view === "radar" && <RadarPanel />}
            {view === "voices" && <VoicesPanel />}
            {view === "inbox" && <InboxPanel />}
            {view === "depots" && <DepotsView />}
            {view === "proof" && <ProofView />}
            {view === "strategies" && <StrategyDashboard />}
            {view === "model" && <ModelPanel />}
            {view === "ml" && <MLSection />}
            {view === "learning" && <LearningCurvePanel />}
            {view === "chat" && <ChatPanel />}
          </div>
        </main>
      </div>
    </>
  );
}
