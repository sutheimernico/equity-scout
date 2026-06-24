import { useState } from "react";

import type { Pick } from "../api";

const FACTORS = ["value", "quality", "momentum", "growth", "low_vol"];

// A single pick. Click toggles a drilldown with the per-factor percentile breakdown + LLM thesis.
export function PickCard({ pick }: { pick: Pick }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card" onClick={() => setOpen((o) => !o)}>
      <div className="card-head">
        <span className="ticker">
          {pick.rank}. {pick.instrument.ticker}
        </span>
        <span className="name">
          {pick.instrument.name} · {pick.instrument.region}
        </span>
        <span className="score">{(pick.composite * 100).toFixed(0)}</span>
      </div>
      <div className="bar">
        <div className="bar-fill" style={{ width: `${pick.composite * 100}%` }} />
      </div>
      {open && (
        <div className="drill">
          {FACTORS.map((f) => (
            <div key={f} className="factor">
              <span className="flabel">{f}</span>
              <div className="fbar">
                <div className="fbar-fill" style={{ width: `${(pick.breakdown[f] ?? 0) * 100}%` }} />
              </div>
              <span className="fval">{((pick.breakdown[f] ?? 0) * 100).toFixed(0)}</span>
            </div>
          ))}
          {pick.thesis && <p className="thesis">{pick.thesis}</p>}
        </div>
      )}
    </div>
  );
}
