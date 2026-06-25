import { useEffect, useState } from "react";

import { fetchForward, type ForwardAccount, type ForwardResponse } from "../api";
import { pct } from "../format";
import { EquityChart } from "./EquityChart";
import { Chip } from "./ui/Chip";
import { Explain } from "./ui/Explain";
import { Metric } from "./ui/Metric";

function AccountBlock({ account }: { account: ForwardAccount }) {
  const cap = account.initial_capital || 1;
  const equitySeries = account.equity_curve.map(([d, e]) => [d, e / cap] as [string, number]);
  const benchSeries = account.equity_curve.map(([d, , b]) => [d, b / cap] as [string, number]);
  const lead = account.total_return - account.benchmark_return;

  return (
    <section className="strat-block">
      <div className="chip-row" style={{ marginBottom: "var(--space-3)" }}>
        <Chip>
          <b>{account.strategy_name}</b>
        </Chip>
        <Chip>
          <b>{account.n_points}</b>&nbsp;{account.n_points === 1 ? "Bewertung" : "Bewertungen"}
        </Chip>
        {account.last_as_of && <Chip>Stand {account.last_as_of}</Chip>}
      </div>

      <div className="metric-grid">
        <Metric label="Rendite (live)" value={pct(account.total_return)} help="Rendite seit Start des Forward-Tracks, nach Kosten." />
        <Metric label={`Benchmark (${account.benchmark_ticker})`} value={pct(account.benchmark_return)} />
        <Metric label="Vorsprung" value={pct(lead)} help="Forward-Rendite minus Benchmark." />
      </div>

      {account.n_points >= 2 ? (
        <EquityChart
          equity={equitySeries}
          benchmark={benchSeries}
          label={account.strategy_name}
          benchmarkLabel={`${account.benchmark_ticker} halten`}
        />
      ) : (
        <Explain tone="hint">
          Der Track baut sich ab jetzt über echte Handelstage auf — die Kurve erscheint, sobald
          mindestens zwei Bewertungen vorliegen. Täglich <code>scripts/run_forward_paper.py</code> laufen lassen.
        </Explain>
      )}
    </section>
  );
}

export function ForwardPanel() {
  const [data, setData] = useState<ForwardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchForward()
      .then(setData)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  return (
    <>
      <Explain>
        Hier laufen die Strategien <strong>fortlaufend vorwärts</strong> — ein echter Track-Record, der
        sich ab dem ersten Lauf über reale Tage aufbaut. Anders als der Backtest (rückwärts über die
        Historie) kann hier <strong>nichts optimiert</strong> worden sein: das ist die ehrlichste
        Evidenz, die es gibt. Nach Kosten, gegen Buy-and-Hold des Benchmarks.
      </Explain>

      {!data.available || data.accounts.length === 0 ? (
        <section className="strat-block">
          <h3 className="block-title">Noch kein Forward-Track</h3>
          <Explain tone="hint">Einmal starten, dann täglich (oder per Cron) fortschreiben:</Explain>
          <p>
            <code>uv run python scripts/run_forward_paper.py --refresh</code>
          </p>
        </section>
      ) : (
        data.accounts.map((acc) => <AccountBlock key={acc.strategy_name} account={acc} />)
      )}
    </>
  );
}
