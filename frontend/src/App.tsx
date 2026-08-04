import { Fragment, useCallback, useEffect, useState } from "react";

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
import { GROUP_LABELS, NAV, parseView, type View } from "./views";

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
  // View lives in the URL so Telegram can deep-link into a focus and a reload keeps it.
  // replaceState (not pushState): the phone's back gesture should leave the app, not walk
  // a tab history the user never built on purpose.
  const [view, setViewState] = useState<View>(() => parseView(window.location.search));
  const setView = useCallback((next: View) => {
    setViewState(next);
    const params = new URLSearchParams(window.location.search);
    params.set("view", next);
    params.delete("token"); // never leave the shared secret in the visible URL
    window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
  }, []);
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
