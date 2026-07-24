import { type StrategySearchBlock, type StrategyTrial } from "../api";
import { num, pct } from "../format";
import { Chip } from "./ui/Chip";
import { Explain } from "./ui/Explain";

const PARAM_LABELS: Record<string, string> = {
  target_vol: "Ziel-Vol",
  vol_window_days: "Vol-Fenster (Tage)",
  lookback_months: "Lookback (Monate)",
  top_n: "Top-N",
  stock_weight: "Aktienquote",
};

function paramsLabel(trial: StrategyTrial): string {
  return Object.entries(trial.params)
    .map(([key, value]) => {
      const label = PARAM_LABELS[key] ?? key;
      const text = Array.isArray(value)
        ? value.join("+")
        : key === "target_vol" || key === "stock_weight"
          ? pct(value)
          : String(value);
      return `${label} ${text}`;
    })
    .join(" · ");
}

function TrialTable({ rows, withRank }: { rows: StrategyTrial[]; withRank?: boolean }) {
  return (
    <div className="table-scroll">
      <table className="history compare">
        <thead>
          <tr>
            {withRank && <th>#</th>}
            <th>Strategie</th>
            <th>Parameter</th>
            <th className="num">DSR</th>
            <th className="num">Sharpe</th>
            <th className="num">Rendite p.a.</th>
            <th className="num">Max. Verlust</th>
            <th className="num">Umschlag/J.</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t, i) => (
            <tr key={`${t.strategy}-${i}`}>
              {withRank && <td className="tnum">{i + 1}</td>}
              <td>{t.name}</td>
              <td>{paramsLabel(t)}</td>
              <td className="num tnum">{num(t.dsr, 2)}</td>
              <td className="num tnum">{num(t.sharpe, 2)}</td>
              <td className="num tnum">{pct(t.cagr)}</td>
              <td className="num tnum">{pct(t.max_drawdown)}</td>
              <td className="num tnum">{num(t.annual_turnover, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// v14: the strategy-parameter pool — own hurdle, in-sample, evidence only.
export function StrategySearchPanel({ block }: { block: StrategySearchBlock }) {
  return (
    <section className="strat-block reveal">
      <h3 className="block-title">Strategie-Parameter-Suche</h3>
      <Explain tone="hint">
        Zweite Suchdimension: die Stellschrauben der Regel-Strategien (Vol-Ziel, Lookbacks,
        Top-N, Aktienquote). <strong>Eigener Versuchs-Pool mit eigener DSR-Hürde</strong> —
        die ML-Suche oben und diese Suche teilen sich nie ein Multiple-Testing-Budget.{" "}
        <strong>In-Sample-Backtests über die volle Historie</strong> (DSR-deflationiert, nach
        Kosten) — Evidenz, keine Empfehlung: die Live-Sleeves behalten ihre Parameter, denn
        geänderte Parameter wären eine neue Strategie-Identität mit frischem Track-Record.
      </Explain>

      {block.n_trials === 0 ? (
        <p className="state">
          Noch keine Versuche — der Nightly-Lauf füllt das Ledger (
          <code>scripts/run_strategy_research.py</code>).
        </p>
      ) : (
        <>
          <div className="chip-row">
            <Chip>
              <b>{block.n_trials}</b>&nbsp;/&nbsp;{block.space_size}&nbsp;Konfigurationen
            </Chip>
            <Chip>
              Eigene Hürde <b>{num(block.hurdle ?? 0, 3)}</b> ↑
            </Chip>
            {block.champion && (
              <Chip>
                Champion-DSR <b>{num(block.champion.dsr, 2)}</b>
              </Chip>
            )}
          </div>
          <TrialTable rows={block.leaderboard} withRank />
          {block.best_per_strategy.length > 1 && (
            <>
              <h3 className="block-title">Beste Parameter je Strategie</h3>
              <TrialTable rows={block.best_per_strategy} />
            </>
          )}
        </>
      )}
    </section>
  );
}
