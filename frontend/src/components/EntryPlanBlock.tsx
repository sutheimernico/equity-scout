import { useEffect, useState } from "react";

import { type EntryPlan, type EntryResponse, fetchEntry } from "../api";
import { pct } from "../format";
import { Bar } from "./ui/Bar";
import { Disclosure } from "./ui/Disclosure";
import { Explain } from "./ui/Explain";

// Map an absolute price onto the 52w low->high range as a [0,1] fraction (for the Bar marker).
function frac(price: number, low: number, high: number): number {
  return high > low ? (price - low) / (high - low) : 0;
}

export function EntryPlanBlock({ ticker }: { ticker: string }) {
  const [state, setState] = useState<EntryResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchEntry(ticker)
      .then((r) => alive && setState(r))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, [ticker]);

  if (error) return <p className="block-hint">Einstiegs-Daten nicht verfügbar.</p>;
  if (!state) return <p className="block-hint">Einstiegs-Levels werden geladen …</p>;
  if (!state.available || !state.plan)
    return <p className="block-hint">Keine ausreichende Kurshistorie für {ticker}.</p>;

  const p: EntryPlan = state.plan;
  const priceFrac = frac(p.price, p.low_52w, p.high_52w);

  return (
    <div className="entry-plan">
      <div className="entry-head">
        <span className="entry-title">Einstiegs-Referenz</span>
        <span className={p.near_reference ? "entry-flag on" : "entry-flag"}>
          {p.near_reference ? "Referenzzone erreicht" : "über Referenzzone"}
        </span>
      </div>
      <Explain tone="hint">{p.reference_note} Kein Kaufsignal, keine Kursprognose.</Explain>

      <div className="entry-range">
        <span className="entry-range-label">
          Kurs {p.price} · 52W {p.low_52w}–{p.high_52w} · vom Hoch {pct(p.drawdown_from_high)}
        </span>
        <Bar value={priceFrac} max={1} marker={{ at: priceFrac, label: "Kurs" }} />
      </div>

      <div className="entry-levels">
        {p.levels.map((lvl) => (
          <div className="entry-level" key={lvl.label} title={lvl.note}>
            <span className="entry-level-name">{lvl.label}</span>
            <Bar
              value={frac(lvl.price, p.low_52w, p.high_52w)}
              max={1}
              tone={lvl.kind === "anchor" ? "accent" : undefined}
              marker={{ at: priceFrac }}
            />
            <span className="entry-level-price tnum">{lvl.price}</span>
          </div>
        ))}
      </div>

      <Disclosure summary="Tranchen-Plan (gestaffelt einsteigen)">
        <Explain tone="info">
          Solider Default: <strong>gestaffeltes DCA</strong> — gleiche Beträge über Zeit. „Buy the
          Dip" verliert historisch in ~70 % der Fälle gegen stures DCA (Maggiulli). Der
          Drawdown-Plan unten ist eine Option ohne nachgewiesenen Edge.
        </Explain>
        <div className="tranche-table">
          <div className="tranche-col">
            <div className="tranche-col-head">DCA · gleichmäßig</div>
            {p.dca_tranches.map((t) => (
              <div className="tranche-row" key={t.label}>
                <span>{t.label}</span>
                <span className="tnum">{Math.round(t.fraction * 100)} %</span>
              </div>
            ))}
          </div>
          <div className="tranche-col">
            <div className="tranche-col-head">Drawdown-Scale-in (Option)</div>
            {p.dip_tranches.map((t) => (
              <div className="tranche-row" key={t.label}>
                <span>{t.label}</span>
                <span className="tnum">
                  {Math.round(t.fraction * 100)} %{t.trigger_price ? ` · ${t.trigger_price}` : ""}
                </span>
              </div>
            ))}
          </div>
        </div>
      </Disclosure>
    </div>
  );
}
