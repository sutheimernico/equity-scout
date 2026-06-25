import { useState } from "react";

import type { Pick } from "../api";
import { FACTOR_LABELS, FACTOR_ORDER, toPercent } from "../format";
import { EntryPlanBlock } from "./EntryPlanBlock";
import { StockChart } from "./StockChart";
import { Badge } from "./ui/Badge";
import { Bar } from "./ui/Bar";

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
  const news = pick.news ?? [];

  return (
    <div className="card" onClick={() => setOpen((isOpen) => !isOpen)}>
      <div className="card-head">
        <span className="rank tnum">{pick.rank}</span>
        <span className="ticker">{pick.instrument.ticker}</span>
        <Badge tone="region">{pick.instrument.region}</Badge>
        {news.length > 0 && <Badge tone="news">📰 {news.length}</Badge>}
        <span className="composite tnum">{toPercent(pick.composite)}</span>
      </div>
      <div className="name">{pick.instrument.name}</div>
      <Bar value={pick.composite} max={1} />

      {open && (
        <div className="drill">
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

          <div onClick={(e) => e.stopPropagation()}>
            <StockChart ticker={pick.instrument.ticker} />
          </div>

          <div onClick={(e) => e.stopPropagation()}>
            <EntryPlanBlock ticker={pick.instrument.ticker} />
          </div>

          {pick.thesis && <p className="thesis">{pick.thesis}</p>}

          {news.length > 0 && (
            <div className="news-list">
              <div className="news-head">Aktuelle News</div>
              {news.map((item, i) => (
                <a
                  className="news-item"
                  key={i}
                  href={item.link || undefined}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                >
                  <span className="news-title">{item.title}</span>
                  <span className="news-meta tnum">
                    {item.publisher}
                    {item.published ? ` · ${item.published}` : ""}
                  </span>
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
