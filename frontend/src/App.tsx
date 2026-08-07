import { Fragment, useCallback, useEffect, useState } from "react";

import { AktienView } from "./components/AktienView";
import { ChatPanel } from "./components/ChatPanel";
import { DepotsView } from "./components/DepotsView";
import { FreshnessBanner } from "./components/FreshnessBanner";
import { InboxPanel } from "./components/InboxPanel";
import { LaborView } from "./components/LaborView";
import { ProofView } from "./components/ProofView";
import { StockProfileView } from "./components/StockProfileView";
import { TodayView } from "./components/TodayView";
import { WerKauftView } from "./components/WerKauftView";
import { WieView } from "./components/WieView";
import { BottomNav } from "./components/BottomNav";
import {
  GROUP_LABELS,
  NAV,
  parseChatOpen,
  parseTicker,
  parseView,
  resolveView,
  type View,
} from "./views";

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

/** Everything routed lives in the URL — view, profile ticker, chat overlay — so
 *  Telegram can deep-link anywhere, a reload keeps the place, and the phone's back
 *  gesture walks back through screens AND closes the overlay/profile (pushState +
 *  popstate, Nico 2026-08-07). */
interface Route {
  view: View;
  ticker: string | null;
  chatOpen: boolean;
}

function readRoute(): Route {
  const search = window.location.search;
  return {
    view: parseView(search),
    ticker: parseTicker(search),
    chatOpen: parseChatOpen(search),
  };
}

export default function App() {
  const [route, setRoute] = useState<Route>(readRoute);

  const push = useCallback((mutate: (params: URLSearchParams) => void) => {
    const params = new URLSearchParams(window.location.search);
    params.delete("token"); // never leave the shared secret in the visible URL
    mutate(params);
    const qs = params.toString();
    window.history.pushState(
      { fromApp: true },
      "",
      `${window.location.pathname}${qs ? `?${qs}` : ""}`,
    );
    setRoute(readRoute());
  }, []);

  const navigate = useCallback(
    (key: string) => {
      const next = resolveView(key);
      if (next === route.view && !route.ticker && !route.chatOpen) return;
      push((params) => {
        params.set("view", next);
        params.delete("ticker"); // navigating away leaves the profile…
        params.delete("chat"); // …and closes the overlay
      });
    },
    [push, route],
  );

  const openStock = useCallback(
    (ticker: string) => {
      push((params) => {
        params.set("view", "profil");
        params.set("ticker", ticker);
        params.delete("chat");
      });
    },
    [push],
  );

  const openChat = useCallback(() => {
    if (route.chatOpen) return;
    push((params) => params.set("chat", "1"));
  }, [push, route.chatOpen]);

  const back = useCallback(() => {
    if (window.history.state?.fromApp) {
      window.history.back();
      return;
    }
    // Deep link straight into a profile/overlay: back would leave the app, so rewrite
    // in place instead.
    const params = new URLSearchParams(window.location.search);
    params.delete("chat");
    params.delete("ticker");
    params.set("view", route.view === "profil" ? "aktien" : route.view);
    const qs = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
    setRoute(readRoute());
  }, [route.view]);

  useEffect(() => {
    // Strip the token from the FIRST history entry too — with pushState the initial entry
    // survives, and the back gesture must never resurface the shared secret in the URL.
    const params = new URLSearchParams(window.location.search);
    if (params.has("token")) {
      params.delete("token");
      const qs = params.toString();
      window.history.replaceState(
        null,
        "",
        `${window.location.pathname}${qs ? `?${qs}` : ""}`,
      );
    }
    const onPop = () => setRoute(readRoute());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  useRevealOnScroll();

  const { view, ticker, chatOpen } = route;

  return (
    <>
      <FreshnessBanner />
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
                  onClick={() => navigate(item.key)}
                >
                  {item.label}
                </button>
              </Fragment>
            ))}
            <span className="nav-sep" aria-hidden="true" />
            <button className="nav-link" onClick={openChat}>
              Assistent
            </button>
          </nav>
        </aside>

        <main className="content">
          <div className="view" key={`${view}:${ticker ?? ""}`}>
            {view === "heute" && <TodayView onNavigate={navigate} onOpenStock={openStock} />}
            {view === "aktien" && <AktienView onOpenStock={openStock} onNavigate={navigate} />}
            {view === "profil" && ticker && (
              <StockProfileView ticker={ticker} onBack={back} onNavigate={navigate} />
            )}
            {view === "entscheiden" && <InboxPanel onOpenStock={openStock} />}
            {view === "depot" && <DepotsView onNavigate={navigate} />}
            {view === "ergebnisse" && <ProofView />}
            {view === "werkauft" && <WerKauftView />}
            {view === "labor" && <LaborView />}
            {view === "wie" && <WieView />}
          </div>
        </main>
      </div>

      {!chatOpen && (
        <button className="chat-fab" onClick={openChat} aria-label="Assistent öffnen">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 12a8 8 0 0 1-8 8H5l-2 2V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8z" />
            <path d="M8.5 11h.01M12.5 11h.01M16.5 11h.01" />
          </svg>
        </button>
      )}
      {chatOpen && (
        <div className="chat-overlay" role="dialog" aria-label="Assistent">
          <ChatPanel overlay onClose={back} />
        </div>
      )}

      <BottomNav view={view} onNavigate={navigate} onOpenChat={openChat} />
    </>
  );
}
