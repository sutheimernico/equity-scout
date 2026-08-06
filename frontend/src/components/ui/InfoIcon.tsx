// The "explain this" affordance. Same stroke language as Chevron and the tab icons (1.6 px,
// round caps, 24-unit grid, currentColor) so the phone has one icon set, not three.
//
// Rendered inside a button that carries the accessible name, hence aria-hidden here.

export function InfoIcon() {
  return (
    <svg
      className="info-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={true}
    >
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5.5" />
      <path d="M12 7.8v.4" />
    </svg>
  );
}
