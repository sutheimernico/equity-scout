import { useEffect, useState } from "react";

import { fetchDiversification, type DiversificationResponse } from "../api";

// „Schlägt das den Markt?" — die Frage, die hinter dem ganzen Projekt steht, mit der
// gemessenen Antwort statt mit einer Hoffnung. Sie steht bewusst GANZ OBEN in den
// Ergebnissen: wer sich durch acht Bücher liest, um sie am Ende selbst zu ziehen, zieht
// sie meistens gar nicht.
function num(value: number | undefined, digits = 2): string {
  return value === undefined ? "—" : value.toFixed(digits).replace(".", ",");
}

export function HonestVerdict() {
  const [data, setData] = useState<DiversificationResponse | null>(null);

  useEffect(() => {
    let ignore = false;
    fetchDiversification()
      .then((r) => {
        if (!ignore) setData(r);
      })
      .catch(() => undefined);
    return () => {
      ignore = true;
    };
  }, []);

  if (!data?.available || !data.schemes || !data.vol_matched) return null;

  const spy = data.schemes["SPY (Benchmark)"];
  const depot = data.schemes["gleichgewichtet"];
  const matched = data.vol_matched;
  if (!spy || !depot) return null;

  const beatsMarket = matched.cagr_pct > spy.cagr_pct;

  return (
    <section className="strat-block verdict reveal">
      <h3 className="block-title">Schlägt das den Markt?</h3>
      <p className="verdict-answer">{beatsMarket ? "Ja." : "Nein — und zwar nicht knapp."}</p>
      <p className="muted">
        Über {num(8, 0)} Jahre Rückrechnung liefert das Strategie-Depot{" "}
        <b>{num(depot.cagr_pct)} % pro Jahr</b> gegenüber <b>{num(spy.cagr_pct)} %</b> für den
        Markt. Das ist aber kein fairer Vergleich, denn das Depot trägt nur halb so viel
        Risiko. Rechnet man es auf dasselbe Risiko hoch — inklusive der{" "}
        {num(matched.financing_rate * 100, 0)} % Zinsen, die man dafür zahlen müsste —, bleiben{" "}
        <b>{num(matched.cagr_pct)} %</b> gegen <b>{num(spy.cagr_pct)} %</b>.
      </p>
      <p className="muted">
        <b>Was es stattdessen kann:</b> ungefähr zwei Drittel der Marktrendite bei{" "}
        <b>halbem Risiko</b> — Schwankung {num(depot.vol_pct)} % statt {num(spy.vol_pct)} %,
        größter Rückgang {num(Math.abs(depot.max_drawdown_pct), 1)} % statt{" "}
        {num(Math.abs(spy.max_drawdown_pct), 1)} %. Das ist ein anderes Produkt als „schlägt
        den Markt", aber ein echtes.
      </p>
      <dl className="brief-detail">
        <dt>Unabhängige Wetten</dt>
        <dd>
          <span className="num">{num(data.effective_bets)}</span> von {data.sleeve_count} —
          die Strategien überschneiden sich stark (mittlere Korrelation{" "}
          {num(data.mean_pairwise_correlation)}).
        </dd>
        <dt>Gemessen am</dt>
        <dd className="tnum">{data.measured_at}</dd>
      </dl>
    </section>
  );
}
