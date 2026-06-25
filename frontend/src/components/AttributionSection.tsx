import { type Attribution } from "../api";
import { ML_FEATURE_LABELS, num, pctAbs } from "../format";
import { Disclosure } from "./ui/Disclosure";

// Self-analysis of the meta-model: where it was wrong, and in what regime.
export function AttributionSection({ attribution }: { attribution: Attribution }) {
  if (attribution.n_bets === 0) return null;
  const contrast = Object.entries(attribution.regime_contrast);

  return (
    <Disclosure
      summary={`Selbstanalyse — ${attribution.n_errors} von ${attribution.n_bets} Entscheidungen lagen daneben`}
    >
      <p>
        In welchem <strong>Regime</strong> lag das Modell daneben? Der Ø-Merkmalswert bei richtigen vs.
        falschen Entscheidungen — der Kontrast zeigt, wann man dem Modell weniger trauen sollte.
      </p>
      <table className="history">
        <thead>
          <tr>
            <th>Merkmal</th>
            <th className="num">Ø bei richtig</th>
            <th className="num">Ø bei falsch</th>
          </tr>
        </thead>
        <tbody>
          {contrast.map(([feature, v]) => (
            <tr key={feature}>
              <td>{ML_FEATURE_LABELS[feature] ?? feature}</td>
              <td className="num tnum">{v.correct === null ? "–" : num(v.correct, 3)}</td>
              <td className="num tnum">{v.wrong === null ? "–" : num(v.wrong, 3)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p>
        Die <strong>selbstsichersten Fehlentscheidungen</strong> (ein überzeugter Irrtum ist der lehrreichste):
      </p>
      <table className="history">
        <thead>
          <tr>
            <th>Datum</th>
            <th>Entscheidung</th>
            <th className="num">P(folgen)</th>
            <th>Tatsächlicher Ausgang</th>
          </tr>
        </thead>
        <tbody>
          {attribution.worst.map((b) => (
            <tr key={b.date}>
              <td className="tnum">{b.date}</td>
              <td>{b.decision === "follow" ? "gefolgt" : "gemieden"}</td>
              <td className="num tnum">{pctAbs(b.probability, 0)}</td>
              <td>{b.label === 1 ? "stieg (Gewinn-Barriere)" : "fiel (Stop)"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Disclosure>
  );
}
