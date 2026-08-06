// Stroke icons for the phone tab bar, replacing the emoji glyphs (Nico 2026-08-06: "die
// Symbole sehen noch nicht wirklich clean aus … vielleicht ein bisschen abgerundet").
//
// Why hand-drawn SVG rather than an icon package: five icons do not justify a dependency,
// and emoji were the actual problem — they render in the OS font, so their weight, colour
// and optical size are outside our control and never match the text beside them. These
// inherit `currentColor`, carry one consistent 1.6 stroke with round caps and joins, and
// sit on the same 24-unit grid, so the row reads as one set.
//
// aria-hidden throughout: every tab already has its visible label, so an accessible name
// here would be read twice.

const COMMON = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export type TabIconName = "today" | "depots" | "inbox" | "proof" | "more";

export function TabIcon({ name }: { name: TabIconName }) {
  switch (name) {
    // Today: a house — the start page.
    case "today":
      return (
        <svg {...COMMON} className="tab-icon">
          <path d="M4 10.5 12 4l8 6.5" />
          <path d="M6 10v9.5h12V10" />
        </svg>
      );
    // Depots: a rounded bar chart — the books and what they hold.
    case "depots":
      return (
        <svg {...COMMON} className="tab-icon">
          <path d="M5 19V12" />
          <path d="M12 19V6" />
          <path d="M19 19v-4.5" />
        </svg>
      );
    // Decide: an inbox tray with a lid line, the pitches waiting for a call.
    case "inbox":
      return (
        <svg {...COMMON} className="tab-icon">
          <path d="M4 13.5 6.5 6h11L20 13.5" />
          <path d="M4 13.5h4l1 2.5h6l1-2.5h4v3.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17z" />
        </svg>
      );
    // Proof: a check inside a rounded square — the measured track record.
    case "proof":
      return (
        <svg {...COMMON} className="tab-icon">
          <rect x="4" y="4" width="16" height="16" rx="4" />
          <path d="M8.5 12.5l2.5 2.5 4.5-5" />
        </svg>
      );
    // More: three dots.
    case "more":
      return (
        <svg {...COMMON} className="tab-icon">
          <circle cx="6" cy="12" r="1.2" fill="currentColor" stroke="none" />
          <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
          <circle cx="18" cy="12" r="1.2" fill="currentColor" stroke="none" />
        </svg>
      );
  }
}
