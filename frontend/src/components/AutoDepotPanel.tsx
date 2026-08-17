import { useEffect, useState } from "react";

import {
  fetchAutodepot,
  type AutodepotResponse,
  type AutodepotSleeveWeight,
} from "../api";
import { eur, num, pct } from "../format";
import { EquityChart } from "./EquityChart";
import { Chip } from "./ui/Chip";
import { Explain } from "./ui/Explain";
import { Metric } from "./ui/Metric";

const BREAKER_LABEL: Record<number, string> = {
  1: "Drawdown-Breaker aktiv: halbes Exposure",
  2: "Drawdown-Breaker aktiv: komplett Cash",
};

function SleeveList({ sleeves }: { sleeves: AutodepotSleeveWeight[] }) {
  return (
    <table className="history">
      <thead>
        <tr>
          <th>Sleeve</th>
          <th>Gewicht</th>
          <th>Sharpe (63T)</th>
        </tr>
      </thead>
      <tbody>
        {sleeves.map((s) => (
          <tr key={s.strategy_name}>
            <td>{s.strategy_name}</td>
            <td>{pct(s.weight, 1)}</td>
            {/* anchor mode never estimated a Sharpe — an empty cell is the honest value */}
            <td>{s.sharpe === null ? "—" : num(s.sharpe, 2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AutoDepotPanel() {
  const [data, setData] = useState<AutodepotResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAutodepot()
      .then(setData)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  if (!data.available || !data.account) {
    return (
      <section className="strat-block">
        <h3 className="block-title">Noch kein Auto-Depot</h3>
        <Explain tone="hint">
          Das Auto-Depot entsteht mit dem ersten nächtlichen Lauf (nightly_train.sh) — oder sofort
          per Hand:
        </Explain>
        <p>
          <code>uv run python scripts/run_autotrader.py</code>
        </p>
      </section>
    );
  }

  const account = data.account;
  const latest = data.latest ?? null;
  const curve = data.equity_curve ?? [];
  const cap = account.initial_capital || 1;
  const equitySeries = curve.map(([d, e]) => [d, e / cap] as [string, number]);
  const benchSeries = curve.map(([d, , b]) => [d, b / cap] as [string, number]);
  const lead = account.total_return - account.benchmark_return;
  const sleeves = data.sleeve_weights ?? [];
  const trades = data.trades ?? [];
  const riskEvents = data.risk_events ?? [];

  return (
    <>
      <Explain>
        <strong>Ein</strong> automatisch gehandeltes Meta-Depot über alle Strategie-Sleeves: die
        Sleeve-Gewichte kommen aus dem eigenen Forward-Track-Record (Equal-Weight-Anker +
        Sharpe-Tilt, monatlich), darüber liegt ein Risk-Layer (Einzeltitel-Limit, Markt-Ampel,
        Vol-Ziel, Drawdown-Breaker). Fills zum Schlusskurs, nach Kosten — Spielgeld, kein
        Edge-Versprechen.
      </Explain>

      <section className="strat-block">
        <div className="chip-row" style={{ marginBottom: "var(--space-3)" }}>
          {account.last_as_of && <Chip>Stand {account.last_as_of}</Chip>}
          <Chip>
            {account.sleeve_mode === "anchor" ? "Anker-Phase (Equal-Weight)" : "Inverse-Vol-Tilt aktiv"}
          </Chip>
          {latest && <Chip>Exposure {pct(latest.gross_exposure, 0)}</Chip>}
        </div>

        {BREAKER_LABEL[account.breaker_stage] && (
          <Explain tone="hint">
            ⛔ {BREAKER_LABEL[account.breaker_stage]}
            {account.breaker_changed_at ? ` (seit ${account.breaker_changed_at})` : ""} — Erholung
            stufenweise nach Cooldown.
          </Explain>
        )}

        <div className="metric-grid">
          <Metric
            label="Rendite (live)"
            value={pct(account.total_return)}
            help="Rendite seit Start des Auto-Depots, nach Kosten."
          />
          <Metric label={`Benchmark (${account.benchmark_ticker})`} value={pct(account.benchmark_return)} />
          <Metric label="Vorsprung" value={pct(lead)} help="Depot-Rendite minus Benchmark." />
          {latest && (
            <Metric
              label="Drawdown"
              value={pct(latest.drawdown)}
              help="Abstand vom bisherigen Höchststand — der Drawdown-Breaker reagiert gestuft ab 10 %."
            />
          )}
          {latest?.equity_eur != null && (
            <Metric
              label="Wert in EUR"
              value={eur(latest.equity_eur)}
              help="Umrechnung zum Tages-Spot (kein Hedge). Der Währungseffekt ist Anzeige, nie Teil der Strategie-Rendite."
            />
          )}
        </div>

        {curve.length >= 2 ? (
          <EquityChart
            equity={equitySeries}
            benchmark={benchSeries}
            label="Auto-Depot"
            benchmarkLabel={`${account.benchmark_ticker} halten`}
          />
        ) : (
          <Explain tone="hint">
            Der Track baut sich ab jetzt über echte Handelstage auf — die Kurve erscheint, sobald
            mindestens zwei Bewertungen vorliegen.
          </Explain>
        )}
      </section>

      <section className="strat-block">
        <h3 className="block-title">Sleeve-Gewichte</h3>
        {account.sleeve_mode === "anchor" && (
          <Explain tone="hint">
            Anker-Phase: alle Sleeves gleichgewichtet — für einen ehrlichen Performance-Tilt braucht
            der Allocator erst ~3 Monate überlappende Forward-Historie aller Sleeves.
          </Explain>
        )}
        {sleeves.length > 0 ? (
          <SleeveList sleeves={sleeves} />
        ) : (
          <p className="state">Noch keine Gewichte persistiert.</p>
        )}
      </section>

      <section className="strat-block">
        <h3 className="block-title">Trades (zuletzt)</h3>
        {trades.length > 0 ? (
          <table className="history">
            <thead>
              <tr>
                <th>Datum</th>
                <th>Ticker</th>
                <th>Δ Gewicht</th>
                <th>Volumen (USD)</th>
                <th>Kosten (USD)</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={`${t.created_at}-${t.ticker}`}>
                  <td>{t.created_at}</td>
                  <td>
                    {t.delta_weight > 0 ? "↑" : "↓"} {t.ticker}
                  </td>
                  <td>{pct(t.delta_weight)}</td>
                  <td>{num(t.notional, 0)}</td>
                  <td>{num(t.cost, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="state">Noch keine Trades gebucht.</p>
        )}
      </section>

      {riskEvents.length > 0 && (
        <section className="strat-block">
          <h3 className="block-title">Risk-Layer-Eingriffe</h3>
          <ul>
            {riskEvents.map((e, i) => (
              <li key={`${e.created_at}-${e.protection}-${i}`}>
                {e.created_at} · ⚠ {e.detail}
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="state">{data.disclaimer}</p>
    </>
  );
}
