import { type ReactNode } from "react";

// Status chip: state as form, not a naked number. `live` adds a pulsing dot for running state.
export function Chip({ live = false, children }: { live?: boolean; children: ReactNode }) {
  return (
    <span className={live ? "chip chip--live" : "chip"}>
      {live && <span className="chip-pulse" aria-hidden="true" />}
      {children}
    </span>
  );
}
