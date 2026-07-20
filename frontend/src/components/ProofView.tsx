import { useEffect, useState } from "react";

import { fetchProof, type ProofBook, type ProofResponse } from "../api";
import { num, pct } from "../format";
import { Explain } from "./ui/Explain";

// v12 P2: the "kann das funktionieren?"-view. Every metric that cannot be computed yet
// renders as "—" with the reason living in the verdict label — the page never pretends.

function metric(value: number | null, digits = 2, suffix = ""): string {
  return value === null ? "—" : `${num(value, digits)}${suffix}`;
}

function BookCard({ book }: { book: ProofBook }) {
  const positive = book.vs_benchmark_pct !== null && book.vs_benchmark_pct > 0;
  return (
    <section className="strat-block">
      <h3>{book.label}</h3>
      <p>
        <b>{positive ? "🟢" : book.vs_benchmark_pct === null ? "⚪" : "🔴"} {book.verdict_label}</b>
      </p>
      {book.period && <p className="section-sub">Zeitraum: {book.period} ({book.n_days} Tage)</p>}
      <table className="history">
        <thead>
          <tr>
            <th>Gesamt</th>
            <th>CAGR</th>
            <th>Sharpe (p.a.)</th>
            <th>Max. Drawdown</th>
            <th>Trefferquote</th>
            <th>Kostenanteil</th>
            <th>vs. Benchmark</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{metric(book.total_return_pct, 1, " %")}</td>
            <td>{metric(book.cagr_pct, 1, " %")}</td>
            <td>{metric(book.sharpe_annualised)}</td>
            <td>{metric(book.max_drawdown_pct, 1, " %")}</td>
            <td>{book.realized_win_rate === null ? "—" : pct(book.realized_win_rate, 0)}</td>
            <td>{book.cost_share_of_pnl === null ? "—" : pct(book.cost_share_of_pnl, 0)}</td>
            <td>{metric(book.vs_benchmark_pct, 1, " %-Pkt.")}</td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}

export function ProofView() {
  const [data, setData] = useState<ProofResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    fetchProof()
      .then((d) => {
        if (!ignore) setData(d);
      })
      .catch((e: unknown) => {
        if (!ignore) setError(String(e));
      });
    return () => {
      ignore = true;
    };
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Entscheiden · Beweis</p>
        <h1>Kann das funktionieren?</h1>
        <p className="section-sub">
          Ehrliche Bilanz jedes Papier-Buchs — gemessen, nicht versprochen. Kennzahlen, die der
          Track Record noch nicht hergibt, stehen als „—" da statt geschätzt zu werden.
        </p>
      </header>

      {data.conviction && (
        <Explain tone="hint">
          Was würde den Einsatz von echtem Geld rechtfertigen? Mindestens{" "}
          <b>{data.conviction.min_track_days} Tage</b> Track Record, Sharpe nach Kosten{" "}
          <b>&gt; {data.conviction.min_sharpe_after_costs}</b>, max. Drawdown{" "}
          <b>&lt; {data.conviction.max_drawdown_pct} %</b> — und selbst dann bleibt es deine
          Entscheidung, nicht die des Systems.
        </Explain>
      )}

      {!data.available && (
        <p className="state">Noch keine Bücher mit genug Historie — die Beweise wachsen täglich.</p>
      )}
      {data.books?.map((book) => <BookCard key={book.label} book={book} />)}

      <Explain tone="hint">{data.disclaimer}</Explain>
    </>
  );
}
