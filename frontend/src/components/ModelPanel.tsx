import { useEffect, useState } from "react";

import { fetchModel, type ModelResponse, type RegistryEntry } from "../api";
import { num, pct, pctAbs } from "../format";
import { Badge } from "./ui/Badge";
import { Bar } from "./ui/Bar";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { Metric } from "./ui/Metric";

// OOS metric key → German label + formatter. A null metric renders "—", never a fabricated number.
const METRIC_META: Record<string, { label: string; fmt: (v: number) => string }> = {
  auc: { label: "Trefferwahrscheinlichkeit (AUC, OOS)", fmt: (v) => pctAbs(v, 1) },
  brier: { label: "Brier-Score", fmt: (v) => num(v, 3) },
  rank_ic: { label: "Rang-IC", fmt: (v) => num(v, 3) },
};
const METRIC_ORDER = ["auc", "brier", "rank_ic"] as const;

// null / missing → "—". This is the honesty rule: no invented number stands in for a missing metric.
function metricValue(metrics: Record<string, number | null>, key: string): string {
  const v = metrics[key];
  return v === null || v === undefined ? "—" : (METRIC_META[key]?.fmt(v) ?? num(v, 3));
}

// ISO timestamp → compact "YYYY-MM-DD HH:MM".
function formatStamp(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

function RegistryRow({ entry }: { entry: RegistryEntry }) {
  return (
    <tr className={entry.is_champion ? "is-champion" : undefined}>
      <td>v{entry.version}</td>
      <td>{formatStamp(entry.created_at)}</td>
      <td>{entry.model_kind}</td>
      <td className="num">{num(entry.n_train, 0)}</td>
      <td className="num">{metricValue(entry.metrics, "auc")}</td>
      <td>{entry.is_champion && <Badge>Champion</Badge>}</td>
    </tr>
  );
}

export function ModelPanel() {
  const [data, setData] = useState<ModelResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // `ignore` guards against a setState after the effect is torn down (unmount / refire).
    let ignore = false;
    fetchModel()
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

  if (!data.available) {
    return (
      <>
        <header className="section-head reveal">
          <p className="eyebrow">Modell</p>
          <h1>Meta-Modell — Ehrlichkeit zuerst</h1>
        </header>
        <p className="state">
          Noch kein Modell trainiert — <code>run_train_entry.py</code> ausführen.
        </p>
      </>
    );
  }

  const { champion, registry, resolved } = data;
  const buckets = Object.entries(resolved.by_score_bucket);
  const maxAbs = buckets.reduce((m, [, v]) => Math.max(m, Math.abs(v)), 0) || 1;

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Modell</p>
        <h1>Meta-Modell — Ehrlichkeit zuerst</h1>
      </header>

      <div className="model-banner reveal" role="note">
        Der Score bewertet die Einstiegs-Attraktivität (Out-of-Sample), ist keine Prognose und keine
        Anlageberatung.
      </div>

      {champion && (
        <section className="strat-block reveal">
          <h3 className="block-title">Champion-Modell</h3>
          <p className="block-hint">
            v{champion.version} · {champion.model_kind} · Stand {formatStamp(champion.created_at)}
          </p>
          <div className="metric-grid">
            {METRIC_ORDER.map((key) => (
              <Metric key={key} label={METRIC_META[key].label} value={metricValue(champion.metrics, key)} />
            ))}
          </div>
        </section>
      )}

      {registry.length > 0 && (
        <section className="strat-block">
          <h3 className="block-title">Modell-Registry</h3>
          <div className="table-scroll">
            <table className="model-table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Erstellt</th>
                  <th>Modell</th>
                  <th className="num">Trainingsdaten</th>
                  <th className="num">AUC (OOS)</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {registry.map((r) => (
                  <RegistryRow key={r.version} entry={r} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="strat-block">
        <h3 className="block-title">Aufgelöste Vorhersagen</h3>
        <div className="metric-grid">
          <Metric label="Aufgelöst" value={num(resolved.n_resolved, 0)} help="Vorhersagen, deren Horizont abgelaufen ist." />
          <Metric label="Offen" value={num(resolved.n_open, 0)} help="Vorhersagen, die noch laufen." />
          <Metric
            label="Trefferquote"
            value={resolved.n_resolved === 0 || resolved.hit_rate === null ? "—" : pctAbs(resolved.hit_rate, 1)}
          />
          <Metric label="Rang-IC" value={resolved.rank_ic === null ? "—" : num(resolved.rank_ic, 3)} />
        </div>

        {resolved.n_resolved === 0 ? (
          <p className="block-hint">
            Noch keine aufgelösten Vorhersagen — die erste Auswertung erscheint, sobald ein
            Vorhersage-Horizont abgelaufen ist.
          </p>
        ) : buckets.length === 0 ? (
          <p className="block-hint">Noch keine Auswertung je Score-Bucket.</p>
        ) : (
          <div className="model-buckets">
            <p className="model-buckets-cap">
              Mittlere realisierte Relativ-Rendite je Score-Bucket — zahlt sich ein höherer Score aus?
            </p>
            {buckets.map(([bucket, v]) => (
              <div className="model-bucket" key={bucket}>
                <span className="model-bucket-label">{bucket}</span>
                <Bar value={Math.abs(v)} max={maxAbs} tone={v < 0 ? "neg" : undefined} />
                <span className={v < 0 ? "tnum neg" : "tnum pos"}>{pct(v)}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <DisclaimerBar text={data.disclaimer} />
    </>
  );
}
