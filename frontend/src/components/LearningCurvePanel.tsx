import { useEffect, useState } from "react";

import {
  fetchModelHistory,
  type DailyCurvePoint,
  type ModelHistoryPoint,
  type ModelHistoryResponse,
} from "../api";
import { Chip } from "./ui/Chip";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { Explain } from "./ui/Explain";

const FAMILY_LABELS: Record<string, string> = {
  entry: "Long-Modell (schlägt SPY?)",
  entry_short: "Short-Modell (verliert gegen SPY?)",
};

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
          className={p.is_champion ? "lc-dot champion" : "lc-dot"}
        >
          <title>{`v${p.version} · AUC ${p.auc?.toFixed(3)} · n=${p.n_oos ?? "?"}`}</title>
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
      </div>
      <AucCurve points={points} />
      <p className="muted">
        Jeder Punkt eine Trainings-Generation (Out-of-Sample-AUC, purged Walk-Forward). Große
        Punkte sind Champions. Kleine n machen einzelne Punkte unzuverlässig — Tooltip zeigt n.
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

      <DisclaimerBar text={data.disclaimer} />
    </>
  );
}
