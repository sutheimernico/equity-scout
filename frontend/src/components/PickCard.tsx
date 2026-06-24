import { useState } from "react";

import type { Pick } from "../api";
import { FACTOR_LABELS, FACTOR_ORDER, toPercent } from "../format";

// One pick. Click toggles a transparency drilldown: for each factor we show its percentile, the
// bucket weight, and the contribution (percentile × weight). The composite is their sum — so the
// headline score is fully traceable.
export function PickCard({ pick, weights }: { pick: Pick; weights: Record<string, number> }) {
  const [open, setOpen] = useState(false);

  const contributions = FACTOR_ORDER.map((factor) => {
    const percentile = pick.breakdown[factor] ?? 0;
    const weight = weights[factor] ?? 0;
    return { factor, percentile, weight, contribution: percentile * weight };
  });
  const compositeFromParts = contributions.reduce((sum, c) => sum + c.contribution, 0);

  return (
    <div className="card" onClick={() => setOpen((isOpen) => !isOpen)}>
      <div className="card-head">
        <span className="rank tnum">{pick.rank}</span>
        <span className="ticker">{pick.instrument.ticker}</span>
        <span className="region-tag">{pick.instrument.region}</span>
        <span className="composite tnum">{toPercent(pick.composite)}</span>
      </div>
      <div className="name">{pick.instrument.name}</div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${toPercent(pick.composite)}%` }} />
      </div>

      {open && (
        <div className="drill">
          <div className="drill-head">
            <span>Factor</span>
            <span>Percentile</span>
            <span>×Wt</span>
            <span>=Contrib</span>
          </div>
          {contributions.map((c) => (
            <div className="factor-row" key={c.factor}>
              <span className="flabel">{FACTOR_LABELS[c.factor]}</span>
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${toPercent(c.percentile)}%` }} />
              </div>
              <span className="fweight tnum">{c.weight.toFixed(2)}</span>
              <span className="fcontrib tnum">{toPercent(c.contribution)}</span>
            </div>
          ))}
          <div className="composite-line">
            <span>Composite = Σ contributions</span>
            <span className="tnum">{toPercent(compositeFromParts)}</span>
          </div>
          {pick.thesis && <p className="thesis">{pick.thesis}</p>}
        </div>
      )}
    </div>
  );
}
