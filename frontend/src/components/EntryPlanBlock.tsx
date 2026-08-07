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

      {state.target_stop ? (
        <span className="entry-range-label">
          <span className="nobr">🎯 Kursziel {state.target_stop.target}</span>
          <span className="nobr">🛑 Stop {state.target_stop.stop}</span>
          <span className="nobr">Horizont {state.target_stop.horizon_days} Handelstage</span>
          {/* Provenance stays visible: a fallback number must never wear the model's badge. */}
          <span className="nobr">
            {state.target_stop.source === "model"
              ? "(trainiertes Modell)"
              : "(konservative Faustformel — noch kein trainiertes Modell)"}
          </span>
        </span>
      ) : (
        <Explain tone="hint">
          Kein Kursziel berechenbar (zu kurze Kurshistorie).
        </Explain>
      )}

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

      <Disclosure summary="Was bedeuten diese Niveaus?">
        <dl className="entry-glossary">
          <dt>Spalte „zum Kurs"</dt>
          <dd>Wie weit das Niveau über (+) oder unter (−) dem aktuellen Kurs liegt.</dd>
          <dt>200-Tage-Schnitt</dt>
          <dd>Der Durchschnittskurs der letzten ~10 Monate — ein grober Anker für „eher teuer / eher günstig".</dd>
          <dt>Fibonacci 38.2 / 50 / 61.8 %</dt>
          <dd>
            Niveaus, an denen ein gefallener Kurs erfahrungsgemäß oft (kurz) Halt findet. Die 61.8 % gelten
            als das „tiefe" Einstiegsniveau. Faustregel, kein Naturgesetz.
          </dd>
          <dt>Jüngstes Tief</dt>
          <dd>Der letzte lokale Tiefpunkt im Kursverlauf — ein technischer Boden.</dd>
          <dt>−1 / −2 ATR</dt>
          <dd>
            Eine bzw. zwei durchschnittliche Tagesschwankungen unter dem aktuellen Kurs — wie tief ein
            ganz normaler Rücksetzer reichen könnte.
          </dd>
        </dl>
      </Disclosure>

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
