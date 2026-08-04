import { Fragment, useState } from "react";

import { GROUP_LABELS, MOBILE_FOCUSES, MOBILE_LABELS, NAV, type View } from "../views";

// Emoji glyphs, not an icon library: the project has no icon set anywhere else, and
// pulling in a dependency to draw four tab glyphs is not worth it.
const FOCUS_ICONS: Record<string, string> = {
  today: "🏠",
  depots: "🤖",
  inbox: "📬",
  proof: "🧾",
};

// Everything that isn't one of the four phone focuses lives in the "Mehr" sheet,
// grouped the same way the sidebar groups them.
const MORE_NAV = NAV.filter((item) => !MOBILE_FOCUSES.includes(item.key));

export function BottomNav({ view, onNavigate }: { view: View; onNavigate: (view: View) => void }) {
  const [sheetOpen, setSheetOpen] = useState(false);

  // "Mehr" reads as active whenever the current view is one of the eight sheet entries —
  // otherwise a deep link straight into e.g. Radar would show no active tab at all.
  const moreActive = !MOBILE_FOCUSES.includes(view);

  const go = (next: View) => {
    onNavigate(next);
    setSheetOpen(false);
  };

  return (
    <>
      <nav className="bottom-nav" aria-label="Hauptnavigation">
        {MOBILE_FOCUSES.map((key) => {
          const active = view === key;
          return (
            <button
              key={key}
              className={active ? "bottom-nav-link active" : "bottom-nav-link"}
              onClick={() => go(key)}
              aria-current={active ? "page" : undefined}
            >
              <span className="bottom-nav-icon" aria-hidden="true">
                {FOCUS_ICONS[key]}
              </span>
              <span className="bottom-nav-label">{MOBILE_LABELS[key]}</span>
            </button>
          );
        })}
        <button
          className={moreActive ? "bottom-nav-link active" : "bottom-nav-link"}
          onClick={() => setSheetOpen((open) => !open)}
          aria-current={moreActive ? "page" : undefined}
          aria-expanded={sheetOpen}
        >
          <span className="bottom-nav-icon" aria-hidden="true">
            ⋯
          </span>
          <span className="bottom-nav-label">Mehr</span>
        </button>
      </nav>

      {sheetOpen && (
        <div className="sheet-backdrop" onClick={() => setSheetOpen(false)}>
          <nav
            className="sheet"
            aria-label="Weitere Ansichten"
            onClick={(e) => e.stopPropagation()}
          >
            {MORE_NAV.map((item, i) => (
              <Fragment key={item.key}>
                {(i === 0 || MORE_NAV[i - 1].group !== item.group) && GROUP_LABELS[item.group] && (
                  <span className="sheet-group">{GROUP_LABELS[item.group]}</span>
                )}
                <button
                  className={view === item.key ? "sheet-link active" : "sheet-link"}
                  onClick={() => go(item.key)}
                  aria-current={view === item.key ? "page" : undefined}
                >
                  {item.label}
                </button>
              </Fragment>
            ))}
          </nav>
        </div>
      )}
    </>
  );
}
