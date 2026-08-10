import { useEffect, useState } from "react";

import {
  fetchModelHistory,
  type DailyCurvePoint,
  type ModelHistoryPoint,
  type ModelHistoryResponse,
} from "../api";
import { Chip } from "./ui/Chip";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { Disclosure } from "./ui/Disclosure";
import { Explain } from "./ui/Explain";

const FAMILY_LABELS: Record<string, string> = {
  entry: "Long-Modell (schlägt SPY?)",
  entry_short: "Short-Modell (verliert gegen SPY?)",
};

/** Tooltip tail for an evidence-featured version. Coverage is carried with it because a
 *  challenger that could only see 2.5 % of the sample has not really been tested yet. */
function evidenceSuffix(p: ModelHistoryPoint): string {
  if (p.evidence_features.length === 0) return "";
  const coverage =
    p.evidence_coverage_91d != null
      ? ` · Abdeckung ${(p.evidence_coverage_91d * 100).toFixed(1)} %`
      : "";
  return ` · mit Evidenz (${p.evidence_features.length} Merkmale)${coverage}`;
}

// Minimal inline AUC-per-version curve: dots on a 0.4–0.8 band with the 0.5 coin-flip line.
// Deliberately unsmoothed — the curve shows what IS, including deterioration.
function AucCurve({ points }: { points: ModelHistoryPoint[] }) {
  const scored = points.filter((p) => p.auc != null);
  if (scored.length === 0) return <p className="muted">Noch keine bewerteten Versionen.</p>;
  const W = 560;
  const H = 120;
  const lo = 0.4;
  const hi = 0.8;
  const x = (i: number) => (scored.length === 1 ? W / 2 : (i / (scored.length - 1)) * (W - 20) + 10);
  const y = (auc: number) => H - ((Math.min(hi, Math.max(lo, auc)) - lo) / (hi - lo)) * H;
  const path = scored.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.auc as number)}`).join(" ");
  return (
    <svg
      className="learning-curve"
      viewBox={`0 0 ${W} ${H + 20}`}
      role="img"
      aria-label="Out-of-Sample-AUC je Trainings-Generation"
    >
      <line x1="0" x2={W} y1={y(0.5)} y2={y(0.5)} className="lc-coinflip" />
      <text x="4" y={y(0.5) - 4} className="lc-label">
        0,50 = Münzwurf
      </text>
      <path d={path} className="lc-path" fill="none" />
      {scored.map((p, i) => (
        <circle
          key={p.version}
          cx={x(i)}
          cy={y(p.auc as number)}
          r={p.is_champion ? 5 : 3}
          className={
            [
              "lc-dot",
              p.is_champion ? "champion" : "",
              // An evidence challenger sits at almost the same AUC as its baseline; without a
              // marker the two dots are one blob and the A/B is invisible (v15 M2).
              p.evidence_features.length > 0 ? "evidence" : "",
            ]
              .filter(Boolean)
              .join(" ")
          }
        >
          <title>{`v${p.version} · AUC ${p.auc?.toFixed(3)} · n=${p.n_oos ?? "?"}${evidenceSuffix(p)}`}</title>
        </circle>
      ))}
    </svg>
  );
}

// Daily learning curve (Strang C, task C1): one point per calendar day (nightly snapshot), so
// training is visible day-to-day instead of only on rare champion-flip events. Same
// dependency-free inline-SVG approach as AucCurve above, but the x-axis is calendar days and the
// y-axis is the ROLLING live hit-rate. Days without a resolved-window reading (hit_rate == null)
// are skipped from the line — an honest gap, not a fake 0.
function DailyCurve({ points }: { points: DailyCurvePoint[] }) {
  if (points.length === 0) {
    return (
      <p className="muted">
        Noch kein Tages-Snapshot — die Kurve startet ehrlich beim ersten nächtlichen
        Trainingslauf, kein rückwirkender Backfill.
      </p>
    );
  }
  const scored = points.filter((p) => p.hit_rate != null);
  if (scored.length === 0) {
    return <p className="muted">Noch keine aufgelösten Vorhersagen im rollierenden Fenster.</p>;
  }
  const W = 560;
  const H = 120;
  const x = (i: number) => (scored.length === 1 ? W / 2 : (i / (scored.length - 1)) * (W - 20) + 10);
  const y = (rate: number) => H - rate * H;
  const path = scored
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.hit_rate as number)}`)
    .join(" ");
  return (
    <svg
      className="learning-curve"
      viewBox={`0 0 ${W} ${H + 20}`}
      role="img"
      aria-label="Tägliche Lernkurve: rollierende Live-Trefferquote pro Kalendertag"
    >
      <line x1="0" x2={W} y1={y(0.5)} y2={y(0.5)} className="lc-coinflip" />
      <text x="4" y={y(0.5) - 4} className="lc-label">
        0,50 = Münzwurf
      </text>
      <path d={path} className="lc-path" fill="none" />
      {scored.map((p, i) => (
        <circle key={p.snapshot_date} cx={x(i)} cy={y(p.hit_rate as number)} r={3} className="lc-dot">
          <title>
            {`${p.snapshot_date} · n_train=${p.n_train ?? "n/a"} · n_resolved=${p.n_resolved ?? 0}` +
              ` · Trefferquote ${((p.hit_rate as number) * 100).toFixed(0)} %` +
              (p.rank_ic != null ? ` · Rank-IC ${p.rank_ic.toFixed(2)}` : "")}
          </title>
        </circle>
      ))}
    </svg>
  );
}

function DailyLearningSection({ points }: { points: DailyCurvePoint[] }) {
  const latest = points.length > 0 ? points[points.length - 1] : null;
  return (
    <section className="strat-block">
      <div className="chip-row" style={{ marginBottom: "var(--space-3)" }}>
        <Chip>
          <b>Tägliche Lernkurve</b>
        </Chip>
        <Chip>
          {points.length} Tages-Snapshot{points.length === 1 ? "" : "s"}
        </Chip>
        {latest && (
          <Chip>n_train zuletzt: {latest.n_train ?? "n/a"}</Chip>
        )}
      </div>
      <DailyCurve points={points} />
      {points.length > 0 && points.length < 5 && (
        <p className="muted">
          Erst {points.length} Snapshot{points.length === 1 ? "" : "s"} seit dem ersten Lauf —
          die Kurve ist noch kurz, wächst aber ehrlich Tag für Tag.
        </p>
      )}
      <p className="muted">
        Ein Punkt pro Kalendertag (nächtlicher Snapshot direkt nach dem Training): n_train des
        aktuellen Champions, rollierende Live-Trefferquote und Rank-IC der aufgelösten
        Vorhersagen. Zeigt tägliches Lernen — nicht nur seltene Champion-Wechsel.
      </p>
    </section>
  );
}

function FamilyBlock({ family, points }: { family: string; points: ModelHistoryPoint[] }) {
  const champion = points.find((p) => p.is_champion);
  const withEvidence = points.filter((p) => p.evidence_features.length > 0);
  // Worst coverage across the evidence versions: the honest headline number, because a
  // challenger is only as tested as the share of the sample its extra features could see.
  const coverage = withEvidence
    .map((p) => p.evidence_coverage_91d)
    .filter((c): c is number => c != null);
  return (
    <section className="strat-block">
      <div className="chip-row" style={{ marginBottom: "var(--space-3)" }}>
        <Chip>
          <b>{FAMILY_LABELS[family] ?? family}</b>
        </Chip>
        <Chip>{points.length} Versionen</Chip>
        {champion ? (
          <Chip>
            Champion v{champion.version} · AUC{" "}
            {champion.auc != null ? champion.auc.toFixed(3) : "—"}
          </Chip>
        ) : (
          <Chip>kein Champion — Gate nicht bestanden</Chip>
        )}
        {withEvidence.length > 0 && <Chip>{withEvidence.length} mit Evidenz-Merkmalen</Chip>}
      </div>
      <AucCurve points={points} />
      <p className="muted">
        Jeder Punkt eine Trainings-Generation (Out-of-Sample-AUC, purged Walk-Forward). Große
        Punkte sind Champions. Kleine n machen einzelne Punkte unzuverlässig — Tooltip zeigt n.
        {withEvidence.length > 0 && (
          <>
            {" "}
            Ringe statt gefüllter Punkte sind Versionen mit Insider-Evidenz-Merkmalen — ein
            bewusster A/B-Vergleich gegen dieselbe Basis
            {coverage.length > 0
              ? `. Abdeckung nur ${(Math.min(...coverage) * 100).toFixed(1)} % der Trainingsdaten: ein Unterschied auf diesem Niveau ist noch kein Befund`
              : ""}
            .
          </>
        )}
      </p>
    </section>
  );
}

export function LearningCurvePanel() {
  const [data, setData] = useState<ModelHistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    fetchModelHistory()
      .then((r) => {
        if (!ignore) setData(r);
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
        <p className="eyebrow">Forschung · Lernkurven</p>
        <h1>Wird das Modell wirklich besser?</h1>
        <p className="section-sub">
          Trainingsfortschritt der ML-Modelle über echte Generationen: Out-of-Sample-Qualität je
          Version, Champion-Wechsel und rollierende Live-Trefferquote. Gemessen, nicht versprochen.
        </p>
      </header>

      <Explain>
        „Fortlaufend lernen" heißt hier: jede Nacht trainieren alle Presets neu, aber ein neuer
        Champion wird nur promotet, wenn er das Gate schlägt (Mindest-AUC-Abstand, Mindest-n,
        kein Münzwurf-Band). Eine flache oder fallende Kurve ist ein ehrliches Ergebnis.
      </Explain>

      <DailyLearningSection points={data.daily_curve} />

      {!data.available ? (
        <p className="state">
          Noch keine registrierten Modelle — <code>run_train_entry.py</code> läuft nächtlich per
          Cron (oder manuell).
        </p>
      ) : (
        Object.entries(data.families).map(([family, points]) => (
          <FamilyBlock key={family} family={family} points={points} />
        ))
      )}

      {data.promotions.length > 0 && (
        <section className="strat-block">
          <h3 className="block-title">Champion-Wechsel</h3>
          <div className="table-scroll">
            <table className="history">
              <thead>
                <tr>
                  <th>Wann</th>
                  <th>Familie</th>
                  <th>Wechsel</th>
                  <th className="num">AUC</th>
                  <th className="num">n</th>
                </tr>
              </thead>
              <tbody>
                {data.promotions.map((p, i) => (
                  <tr key={i}>
                    <td className="tnum">{p.promoted_at ? p.promoted_at.slice(0, 10) : "—"}</td>
                    <td>{FAMILY_LABELS[p.family] ?? p.family}</td>
                    <td>
                      {p.prior_version != null ? `v${p.prior_version} → ` : "erster Champion: "}
                      v{p.version}
                    </td>
                    <td className="num tnum">{p.auc != null ? p.auc.toFixed(3) : "—"}</td>
                    <td className="num tnum">{p.n_oos ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="strat-block">
        <h3 className="block-title">Rollierende Live-Trefferquote (aufgelöste Vorhersagen)</h3>
        {data.resolved_windows.map((w) => (
          <p key={w.window_days} className="muted">
            Letzte {w.window_days} Tage:{" "}
            {w.n_resolved === 0
              ? "keine aufgelösten Vorhersagen"
              : `${(w.hit_rate! * 100).toFixed(0)} % Treffer bei n=${w.n_resolved}` +
                (w.rank_ic != null ? `, Rank-IC ${w.rank_ic.toFixed(2)}` : "")}
          </p>
        ))}
      </section>

      {data.caveats && data.caveats.length > 0 && (
        <Disclosure summary="Methodische Einschränkungen (Backtest vs. Live, Trainingsuniversum)">
          {data.caveats.map((caveat) => (
            <p key={caveat}>{caveat}</p>
          ))}
        </Disclosure>
      )}

      <DisclaimerBar text={data.disclaimer} />
    </>
  );
}
