// The "this row opens" hint. Nico 2026-08-06: "mach am besten, dass es dadrunter
// aufgeklappt wird. Das heißt, dass da irgendwie so ein Pfeil nach unten ist."
//
// The content already expanded underneath — what was missing was any sign that a row could be
// tapped at all. Same stroke language as the tab icons (1.6 px, round caps, 24-unit grid,
// currentColor) rather than a "▾" glyph: the OS font decides an arrow character's weight and
// optical size, which is why the emoji tabs were replaced on 06.08.
//
// The rotation lives in CSS, keyed off the button's aria-expanded, so the open state is
// declared once per row instead of being passed down as a prop.
//
// Not to be confused with `.disclosure-chev`, the "›" glyph inside the <details> elements of
// the desktop views. Those are a different element with a different open mechanism; folding
// them onto this icon belongs to the "Mehr"-views pass (Task 9), not here.

export function Chevron() {
  return (
    <svg
      className="chevron"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={true}
    >
      <path d="M6 9.5 12 15.5 18 9.5" />
    </svg>
  );
}
