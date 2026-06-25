import { useEffect, useState } from "react";

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
  const [view, setView] = useState<View>("strategies");
  useRevealOnScroll();

  return (
    <>
      <div className="aurora" aria-hidden="true" />
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
        <div className="view" key={view}>
          {view === "strategies" && <StrategyDashboard />}
          {view === "ml" && <MLSection />}
          {view === "funnel" && <FunnelView />}
          {view === "chat" && <ChatPanel />}
        </div>
      </main>
    </>
  );
}
