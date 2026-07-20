import { useEffect, useState } from "react";

import { fetchOverview, type OverviewResponse } from "../api";
import { num, pct } from "../format";
import { Explain } from "./ui/Explain";
import { StatTile } from "./StatTile";

// v12 I4: "Wie steht MEIN Gesamtsystem heute?" — one view across all horizons.
// Books that do not exist yet are honestly absent (the API omits them).

const HORIZON_ORDER = ["short", "mid", "long"] as const;

function dayBadge(day: number | null): string {
  if (day === null) return "—";
  return `${day >= 0 ? "🟢" : "🔴"} ${day >= 0 ? "+" : ""}${num(day, 0)} $`;
}

export function OverviewPanel() {
  const [data, setData] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    fetchOverview()
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
  if (!data.available || !data.books || !data.total) {
    return (
      <p className="state">
        Noch keine Bücher vorhanden — sobald Auto-Depot oder Arena Daten schreiben,
        erscheint hier der Gesamtblick.
      </p>
    );
  }

  const total = data.total;
  const totalReturn = total.initial > 0 ? total.equity / total.initial - 1.0 : null;

  return (
    <>
      <div className="kpi-row">
        <StatTile label="Gesamt-Equity (Paper)" value={`${num(total.equity, 0)} $`} />
        <StatTile label="Heute" value={dayBadge(total.day_pnl)} />
        <StatTile
          label="Gesamt-Rendite"
          value={totalReturn === null ? "—" : pct(totalReturn)}
        />
      </div>

      {data.horizons && (
        <section className="strat-block">
          <h3>Nach Horizont</h3>
          <table className="history">
            <thead>
              <tr>
                <th>Horizont</th>
                <th>Equity</th>
              </tr>
            </thead>
            <tbody>
              {HORIZON_ORDER.filter((h) => data.horizons?.[h]).map((h) => {
                const horizon = data.horizons![h];
                return (
                  <tr key={h}>
                    <td>{horizon.label}</td>
                    <td>{num(horizon.equity, 0)} $</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Explain tone="hint">
            Mittel-/Langfrist-Aufteilung ist eine Näherung anteilig nach den
            Sleeve-Gewichten des Auto-Depots.
          </Explain>
        </section>
      )}

      <section className="strat-block">
        <h3>Alle Bücher</h3>
        <table className="history">
          <thead>
            <tr>
              <th>Buch</th>
              <th>Equity</th>
              <th>Heute</th>
              <th>Gesamt</th>
              <th>Stand</th>
            </tr>
          </thead>
          <tbody>
            {data.books.map((book) => (
              <tr key={book.key}>
                <td>{book.label}</td>
                <td>{num(book.equity, 0)} $</td>
                <td>{dayBadge(book.day_pnl)}</td>
                <td>{pct(book.total_return)}</td>
                <td>{book.as_of.slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <Explain tone="hint">{data.disclaimer}</Explain>
    </>
  );
}
