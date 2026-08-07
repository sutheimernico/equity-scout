import { useState } from "react";

import type { Pick } from "../api";
import { shortCompanyName } from "../company";
import { FACTOR_LABELS, FACTOR_ORDER, toPercent } from "../format";
import { EntryPlanBlock } from "./EntryPlanBlock";
import { InsightBlock } from "./InsightBlock";
import { MiniYearChart } from "./MiniYearChart";
import { PotentialBlock } from "./PotentialBlock";
import { StockLogo } from "./StockLogo";
import { Badge } from "./ui/Badge";
import { Bar } from "./ui/Bar";
import { Chevron } from "./ui/Chevron";

function money(value: number, currency: string | null | undefined): string {
  const formatted = value.toLocaleString("de-DE", { maximumFractionDigits: 2 });
  return currency ? `${formatted} ${currency}` : formatted;
}

// One pick, same head grammar as every other stock card (2026-08-07 rebuild): company
// first, today's price + analyst target in the meta line, the chevron says the card
// opens. The drilldown keeps the factor transparency table (percentile × weight =
// contribution, summing to the headline score) and now uses OUR chart + the summarised
// news — the TradingView embed silently rendered nothing for many international tickers.
export function PickCard({ pick, weights }: { pick: Pick; weights: Record<string, number> }) {
  const [open, setOpen] = useState(false);

  const contributions = FACTOR_ORDER.map((factor) => {
    const percentile = pick.breakdown[factor] ?? 0;
    const weight = weights[factor] ?? 0;
    return { factor, percentile, weight, contribution: percentile * weight };
  });
  const compositeFromParts = contributions.reduce((sum, c) => sum + c.contribution, 0);

  return (
    <div className="card">
      <button className="pick-main" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="rank tnum">{pick.rank}</span>
        <StockLogo ticker={pick.instrument.ticker} name={pick.instrument.name} />
        <span className="pitch-ident">
          <span className="pitch-company">{shortCompanyName(pick.instrument.name)}</span>
          {/* Badge on its own line: inside the nowrap ticker span it pushed the pair
              past the column edge and under the potential label. */}
          <span className="ticker">{pick.instrument.ticker}</span>
          <span>
            <Badge tone="region">{pick.instrument.region}</Badge>
          </span>
        </span>
        <PotentialBlock
          upsidePct={pick.analyst_upside_pct ?? null}
          analystCount={pick.analyst_count ?? null}
          yearHighPct={pick.year_high_gap_pct ?? null}
        />
        <Chevron />
      </button>

      <p className="radar-score-label">
        Faktor-Score <b className="tnum">{toPercent(pick.composite)}/100</b> — unser Modell,
        Rang {pick.rank} im Bucket
      </p>
      <Bar value={pick.composite} max={1} />

      {/* Price and analyst target in one line — "es gibt keine Kursziele bei vielen"
          (Nico 2026-08-07): where a consensus target exists it is SHOWN, where none
          exists the absence is said, never padded with a model number we don't have. */}
      <div className="pitch-meta">
        {pick.price !== null && pick.price !== undefined && (
          <span className="nobr">
            Kurs <span className="tnum">{money(pick.price, pick.currency)}</span>
          </span>
        )}
        <span className="nobr">
          Analysten-Ziel{" "}
          {pick.analyst_target !== null && pick.analyst_target !== undefined ? (
            <span className="tnum">{money(pick.analyst_target, pick.currency)}</span>
          ) : (
            "— keine Schätzung"
          )}
        </span>
      </div>

      {open && (
        <div className="drill">
          <MiniYearChart chart={pick.chart ?? null} currency={pick.currency ?? null} />

          <InsightBlock insight={pick.insight} />

          <div className="drill-head">
            <span>Faktor</span>
            <span>Perzentil</span>
            <span>×Gew.</span>
            <span>=Beitrag</span>
          </div>
          {contributions.map((c) => (
            <div className="factor-row" key={c.factor}>
              <span className="flabel">{FACTOR_LABELS[c.factor]}</span>
              <Bar value={c.percentile} max={1} />
              <span className="fweight tnum">{c.weight.toFixed(2)}</span>
              <span className="fcontrib tnum">{toPercent(c.contribution)}</span>
            </div>
          ))}
          <div className="composite-line">
            <span>Score = Summe der Beiträge</span>
            <span className="tnum">{toPercent(compositeFromParts)}</span>
          </div>

          <EntryPlanBlock ticker={pick.instrument.ticker} />

          {pick.thesis && <p className="thesis">{pick.thesis}</p>}
        </div>
      )}
    </div>
  );
}
