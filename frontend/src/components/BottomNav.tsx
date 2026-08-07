import { useState } from "react";

import { MOBILE_FOCUSES, MOBILE_LABELS, NAV, SHEET_NOTES, type View } from "../views";
import { TabIcon, type TabIconName } from "./ui/TabIcon";

// Stroke icons, not emoji (2026-08-06). Emoji render in the OS font, so their weight,
// colour and optical size are outside our control and never match the label beneath them —
// which is exactly what made the row look unfinished ("die Symbole sehen noch nicht
// wirklich clean aus"). Still no dependency: hand-drawn paths, see ui/TabIcon.tsx.
const FOCUS_ICONS: Record<string, TabIconName> = {
  heute: "today",
  aktien: "aktien",
  entscheiden: "inbox",
  depot: "depots",
};

const SHEET_ICONS: Record<string, string> = {
  ergebnisse: "📊",
  werkauft: "🏛",
  wie: "❓",
  labor: "🧪",
};

// Everything in the "mehr" group lives in the sheet, plus the assistant entry.
const MORE_NAV = NAV.filter((item) => item.group === "mehr");

export function BottomNav({
  view,
  onNavigate,
  onOpenChat,
}: {
  view: View;
  onNavigate: (view: string) => void;
  onOpenChat: () => void;
}) {
  const [sheetOpen, setSheetOpen] = useState(false);

  // The profile is a drill-down from the stock list, so the Aktien tab stays lit there.
  const activeFocus: View = view === "profil" ? "aktien" : view;
  // "Mehr" reads as active whenever the current view is one of the sheet entries —
  // otherwise a deep link straight into e.g. Labor would show no active tab at all.
  const moreActive = !MOBILE_FOCUSES.includes(activeFocus);

  const go = (next: string) => {
    onNavigate(next);
    setSheetOpen(false);
  };

  return (
    <>
      <nav className="bottom-nav" aria-label="Hauptnavigation">
        {MOBILE_FOCUSES.map((key) => {
          const active = activeFocus === key;
          return (
            <button
              key={key}
              className={active ? "bottom-nav-link active" : "bottom-nav-link"}
              onClick={() => go(key)}
              aria-current={active ? "page" : undefined}
            >
              <span className="bottom-nav-icon" aria-hidden="true">
                <TabIcon name={FOCUS_ICONS[key]} />
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
            <TabIcon name="more" />
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
            {MORE_NAV.map((item) => (
              <button
                key={item.key}
                className={view === item.key ? "sheet-link active" : "sheet-link"}
                onClick={() => go(item.key)}
                aria-current={view === item.key ? "page" : undefined}
              >
                <span className="sheet-ico" aria-hidden="true">
                  {SHEET_ICONS[item.key] ?? "·"}
                </span>
                <span className="sheet-text">
                  <span className="sheet-title">{item.label}</span>
                  {SHEET_NOTES[item.key] && (
                    <span className="sheet-note">{SHEET_NOTES[item.key]}</span>
                  )}
                </span>
              </button>
            ))}
            <button
              className="sheet-link"
              onClick={() => {
                setSheetOpen(false);
                onOpenChat();
              }}
            >
              <span className="sheet-ico" aria-hidden="true">
                💬
              </span>
              <span className="sheet-text">
                <span className="sheet-title">Assistent</span>
                <span className="sheet-note">
                  Fragen zu deinen Zahlen — beantwortet von lokaler KI.
                </span>
              </span>
            </button>
          </nav>
        </div>
      )}
    </>
  );
}
