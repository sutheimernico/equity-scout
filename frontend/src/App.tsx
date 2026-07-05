import { Fragment, useEffect, useState } from "react";

import { ArenaPanel } from "./components/ArenaPanel";
import { ChatPanel } from "./components/ChatPanel";
import { FunnelView } from "./components/FunnelView";
import { InboxPanel } from "./components/InboxPanel";
import { MLSection } from "./components/MLSection";
import { ModelPanel } from "./components/ModelPanel";
import { RadarPanel } from "./components/RadarPanel";
import { StrategyDashboard } from "./components/StrategyDashboard";

type View = "arena" | "radar" | "inbox" | "model" | "strategies" | "ml" | "funnel" | "chat";

// Copilot surfaces lead (Arena is the headline + default); a separator splits them from the
// research views. `group` change between adjacent items renders the hairline divider.
const NAV: { key: View; label: string; group: "copilot" | "research" }[] = [
  { key: "arena", label: "Arena", group: "copilot" },
  { key: "radar", label: "Radar", group: "copilot" },
  { key: "inbox", label: "Inbox", group: "copilot" },
  { key: "model", label: "Modell", group: "copilot" },
  { key: "strategies", label: "Strategien", group: "research" },
  { key: "ml", label: "Machine Learning", group: "research" },
  { key: "funnel", label: "Aktien-Screener", group: "research" },
  { key: "chat", label: "Assistent", group: "research" },
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
  const [view, setView] = useState<View>("arena");
  useRevealOnScroll();

  return (
    <>
      <div className="aurora" aria-hidden="true" />
      <header className="topbar">
        <span className="brand">
          equity-scout<span className="dot">.</span>
        </span>
        <nav className="nav">
          {NAV.map((item, i) => (
            <Fragment key={item.key}>
              {i > 0 && NAV[i - 1].group !== item.group && (
                <span className="nav-sep" aria-hidden="true" />
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
      </header>

      <main className="content">
        <div className="view" key={view}>
          {view === "arena" && <ArenaPanel />}
          {view === "radar" && <RadarPanel />}
          {view === "inbox" && <InboxPanel />}
          {view === "model" && <ModelPanel />}
          {view === "strategies" && <StrategyDashboard />}
          {view === "ml" && <MLSection />}
          {view === "funnel" && <FunnelView />}
          {view === "chat" && <ChatPanel />}
        </div>
      </main>
    </>
  );
}
