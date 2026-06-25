import { useState } from "react";

import { ETF_NAMES, eur, pctAbs } from "../format";

// "What to buy now" for a strategy: its current target allocation, converted to euro amounts.
// Honest framing: this is the strategy's rule-based target, not investment advice.
export function AllocationAdvisor({ weights }: { weights: Record<string, number> }) {
  const [amount, setAmount] = useState(10000);
  const entries = Object.entries(weights)
    .filter(([, w]) => w > 1e-9)
    .sort((a, b) => b[1] - a[1]);
  const invested = entries.reduce((sum, [, w]) => sum + w, 0);
  const cash = Math.max(0, 1 - invested);
  const maxWeight = entries[0]?.[1] || 1;

  return (
    <section className="strat-block advisor">
      <h3 className="block-title">Konkret umsetzen — was jetzt kaufen</h3>
      <p className="block-hint">
        Die aktuelle Soll-Allokation dieser Strategie, umgerechnet auf deinen Betrag — die
        regelbasierte Vorgabe der Strategie, keine Anlageberatung.
      </p>
      <label className="amount-field">
        Anlagebetrag
        <input
          type="number"
          min={0}
          step={1000}
          value={amount}
          onChange={(e) => setAmount(Math.max(0, Number(e.target.value) || 0))}
        />
        €
      </label>

      {entries.length === 0 ? (
        <p className="muted">Aktuell vollständig in Cash — die Regel empfiehlt gerade keinen Kauf.</p>
      ) : (
        <div className="buy-list">
          {entries.map(([ticker, weight]) => (
            <div className="buy-row" key={ticker}>
              <span className="buy-ticker">{ticker}</span>
              <span className="buy-name">{ETF_NAMES[ticker] ?? ticker}</span>
              <div className="bar-track buy-bar">
                <div className="bar-fill" style={{ width: `${Math.round((weight / maxWeight) * 100)}%` }} />
              </div>
              <span className="buy-pct tnum">{pctAbs(weight, 0)}</span>
              <span className="buy-eur tnum">{eur(weight * amount)}</span>
            </div>
          ))}
          {cash > 0.005 && (
            <div className="buy-row cash-row">
              <span className="buy-ticker">—</span>
              <span className="buy-name">Cash halten</span>
              <div className="bar-track buy-bar">
                <div className="bar-fill cost" style={{ width: `${Math.round((cash / maxWeight) * 100)}%` }} />
              </div>
              <span className="buy-pct tnum">{pctAbs(cash, 0)}</span>
              <span className="buy-eur tnum">{eur(cash * amount)}</span>
            </div>
          )}
        </div>
      )}

      <p className="block-hint advisor-note">
        <strong>Tranchenweise einsteigen?</strong> Bei größeren Beträgen oder Unsicherheit beim
        Zeitpunkt: den Betrag über 3–6 Monate in gleichen Raten investieren (Dollar-Cost-Averaging) —
        das senkt das Risiko, alles zum Höchstkurs zu kaufen. Da die Strategie monatlich rebalanciert,
        passt sich die Allokation ohnehin laufend an.
      </p>
    </section>
  );
}
