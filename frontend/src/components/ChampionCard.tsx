import { type ResearchConfig } from "../api";
import { num, pct, pctAbs, researchConfigLabel } from "../format";
import { Explain } from "./ui/Explain";
import { Metric } from "./ui/Metric";

// The best configuration the research loop has found so far (highest Deflated Sharpe).
export function ChampionCard({ champion }: { champion: ResearchConfig }) {
  return (
    <section className="strat-block">
      <h3 className="block-title">Aktueller Champion</h3>
      <p className="champion-config">{researchConfigLabel(champion)}</p>
      <Explain tone="hint">
        Signal-Lookback {champion.primary_lookback_months} Mon. · Horizont {champion.horizon_days} Tage ·
        Barriere {pctAbs(champion.barrier, 0)}
      </Explain>
      <div className="metric-grid">
        <Metric
          label="DSR"
          value={num(champion.dsr, 2)}
          help="Deflated Sharpe — Konfidenz, dass der Edge echt ist (> 0 übersteht den Zufallstest)."
        />
        <Metric label="Sharpe" value={num(champion.sharpe, 2)} />
        <Metric label="Rendite p.a." value={pct(champion.cagr)} />
        <Metric label="Max. Verlust" value={pct(champion.max_drawdown)} />
        <Metric label="Trefferquote" value={pctAbs(champion.oos_hit_rate, 0)} />
      </div>
    </section>
  );
}
