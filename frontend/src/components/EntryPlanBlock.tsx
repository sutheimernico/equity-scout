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
        {p.near_reference && <span className="entry-flag">Referenzzone erreicht</span>}
      </div>
      <Explain tone="hint">{p.reference_note} Kein Kaufsignal, keine Kursprognose.</Explain>

      <div className="entry-range">
        <span className="entry-range-label">
          <span className="nobr">Kurs {p.price}</span>
          <span className="nobr">52W {p.low_52w}–{p.high_52w}</span>
          <span className="nobr">vom Hoch {pct(p.drawdown_from_high)}</span>
        </span>
        <Bar value={priceFrac} max={1} marker={{ at: priceFrac }} />
      </div>

      <div className="entry-levels">
        <div className="entry-levels-head">
          <span>Referenz-Level</span>
          <span>Preis</span>
          <span>zum Kurs</span>
        </div>
        {p.levels.map((lvl) => (
          <div className="entry-level" key={`${lvl.label}_${lvl.price}`} title={lvl.note}>
            <span className={lvl.kind === "anchor" ? "entry-level-name anchor" : "entry-level-name"}>
              {lvl.label}
            </span>
            <span className="entry-level-price tnum">{lvl.price}</span>
            <span className={`entry-level-delta tnum ${lvl.price < p.price ? "below" : ""}`}>
              {pct(p.price > 0 ? lvl.price / p.price - 1 : 0)}
            </span>
          </div>
        ))}
      </div>

      <Disclosure summary="Tranchen-Plan (gestaffelt einsteigen)">
        <Explain tone="info">
          Solider Default: <strong>gestaffeltes DCA</strong> — gleiche Beträge über die Zeit. „Buy the
          Dip" verliert historisch in ~70 % der Fälle gegen stures DCA (Maggiulli). Der Drawdown-Plan
          ist eine Option ohne nachgewiesenen Edge.
        </Explain>

        <div className="tranche-group">
          <div className="tranche-group-head">Gleichmäßig (DCA) · empfohlen</div>
          <p className="tranche-note">
            {p.dca_tranches.length} gleiche Tranchen à {Math.round((p.dca_tranches[0]?.fraction ?? 0) * 100)} %,
            zeitlich gestaffelt.
          </p>
        </div>

        <div className="tranche-group">
          <div className="tranche-group-head">Bei Drawdown nachkaufen · Option</div>
          <div className="tranche-dip">
            {p.dip_tranches.map((t) => (
              <div className="tranche-dip-row" key={`${t.label}_${t.trigger_price}`}>
                <span className="tranche-dip-label">{t.label}</span>
                <span className="tranche-dip-frac tnum">{Math.round(t.fraction * 100)} %</span>
                <span className="tranche-dip-price tnum">
                  {t.trigger_price != null ? `ab ${t.trigger_price}` : "—"}
                </span>
              </div>
            ))}
          </div>
        </div>
      </Disclosure>
    </div>
  );
}
