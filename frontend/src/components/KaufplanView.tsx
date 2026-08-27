import { useEffect, useState } from "react";

import { fetchKaufplan, type BuyPlan } from "../api";
import { shortCompanyName } from "../company";
import {
  PLAN_FILTERS,
  STANCE_META,
  buyerSummary,
  distanceToLimitPct,
  emptyNote,
  filterPlans,
  type PlanFilter,
} from "../kaufplan";
import { StockLogo } from "./StockLogo";
import { Chevron } from "./ui/Chevron";

// Die Ansicht, nach der Nico wirklich kaufen will (Nachtschicht 2026-08-27). Sie ersetzt
// nichts: die Aktienliste bleibt der schnelle Überblick, hier steht der Plan pro Titel.
//
// Zwei Formregeln, beide aus dem Handy-Umbau vom 2026-08-23 gelernt:
// 1. Nichts Ungedeckeltes. Die Karte ist zugeklappt eine Zeile; alles Weitere kostet einen Tipp.
// 2. Keine Farbe ohne Text daneben. Ein grüner Chip allein ist auf einer Kaufkarte
//    eine Behauptung, die niemand nachlesen kann.

function money(value: number | null, currency: string | null): string {
  if (value === null) return "—";
  return `${value.toLocaleString("de-DE", { maximumFractionDigits: 2 })}${currency ? ` ${currency}` : ""}`;
}

/** Eine Zeile „Etikett — Wert". Fehlt der Wert, sagt sie das, statt zu verschwinden:
 *  eine ausgelassene Zeile liest sich wie „gibt es nicht", eine leere wie „unbekannt". */
function Row({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="plan-row">
      <span className="plan-row-label">{label}</span>
      <span className="plan-row-value">{value}</span>
      {hint && <span className="plan-row-hint">{hint}</span>}
    </div>
  );
}

function PlanCard({ plan }: { plan: BuyPlan }) {
  const [open, setOpen] = useState(false);
  const meta = STANCE_META[plan.entry.stance];
  const distance = distanceToLimitPct(plan);
  const buyers = buyerSummary(plan);
  const hardToReach = plan.tradability.level === "schwer zugänglich";

  return (
    <li className="plan-card">
      <button className="plan-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <StockLogo ticker={plan.ticker} name={plan.name} />
        <span className="plan-head-body">
          <span className="plan-name" title={plan.name}>
            {shortCompanyName(plan.name)}
          </span>
          <span className="plan-chiprow">
            <span className={meta.chip}>{meta.label}</span>
            {plan.score !== null && <span className="plan-chip plan-chip-mute">Score {plan.score}</span>}
            {hardToReach && <span className="plan-chip plan-chip-warn">schwer handelbar</span>}
          </span>
        </span>
        <span className="plan-head-limit">
          <span className="plan-limit-value">{money(plan.entry.limit, plan.currency)}</span>
          <span className="plan-limit-label">
            {plan.entry.limit === null ? "kein Limit" : "Kauflimit"}
          </span>
        </span>
        <Chevron />
      </button>

      <p className="plan-stance-note">{plan.entry.stance_note}</p>

      {open && (
        <div className="plan-body">
          <section className="plan-block">
            <h3>Einstieg</h3>
            <Row label="Kurs jetzt" value={money(plan.price, plan.currency)} />
            <Row
              label="Kauflimit"
              value={money(plan.entry.limit, plan.currency)}
              hint={
                distance === null
                  ? undefined
                  : `Kurs steht ${distance >= 0 ? "+" : "−"}${Math.abs(distance).toFixed(1)} % dazu`
              }
            />
            <Row
              label="Stützbereich"
              value={`${money(plan.entry.zone_low, null)} – ${money(plan.entry.zone_high, plan.currency)}`}
            />
            {plan.entry.tranches.length > 0 ? (
              <>
                <p className="plan-sub">In Schritten kaufen — das glättet den Einstiegspreis:</p>
                <ul className="plan-tranches">
                  {plan.entry.tranches.map((t) => (
                    <li key={t.label}>
                      <span>{t.label}</span>
                      <span>{money(t.trigger_price, plan.currency)}</span>
                      <span>{Math.round(t.share * 100)} %</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="plan-sub">
                Keine Einstiegsleiter: unter einem gebrochenen Stützbereich gibt es keinen
                Einstieg zu staffeln.
              </p>
            )}
            <p className="plan-sub">{plan.sizing.note}</p>
          </section>

          <section className="plan-block">
            <h3>Verkaufen — und wann nicht</h3>
            <Row
              label="Kursziel"
              value={money(plan.exit.target, plan.currency)}
              hint={
                plan.exit.target_source === "model"
                  ? "trainiertes Modell"
                  : plan.exit.target_source === "heuristic_v1"
                    ? "Faustregel, kein trainiertes Modell"
                    : undefined
              }
            />
            <Row label="Stop" value={money(plan.exit.stop, plan.currency)} />
            {plan.exit.analyst_target !== null && (
              <Row
                label="Analystenziel"
                value={money(plan.exit.analyst_target, plan.currency)}
                hint={`${plan.exit.analyst_count ?? 0} Schätzungen — fremde Meinung, oft falsch`}
              />
            )}
            <p className="plan-sub">{plan.exit.hold_note}</p>
            <p className="plan-sub">
              Grundregeln: bei +{plan.exit.profit_target_pct.toFixed(0)} % verkaufen, bei −
              {plan.exit.stop_loss_pct.toFixed(0)} % aussteigen, spätestens nach{" "}
              {plan.exit.max_holding_days} Tagen prüfen.
            </p>
          </section>

          {plan.business && (
            <section className="plan-block">
              <h3>Was die Firma macht</h3>
              <p className="plan-sub">{plan.business}</p>
            </section>
          )}

          {plan.why.length > 0 && (
            <section className="plan-block">
              <h3>Warum sie im Screen steht</h3>
              <ul className="plan-why">
                {plan.why.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              <p className="plan-sub">
                Berechnete Faktorwerte, keine Einschätzung — sie sagen, warum der Titel
                aufgefallen ist, nicht ob er steigt.
              </p>
            </section>
          )}

          <section className="plan-block">
            <h3>Handelbarkeit</h3>
            <p className="plan-sub">{plan.tradability.note}</p>
          </section>

          {plan.buyers.length > 0 && (
            <section className="plan-block">
              <h3>Wer gekauft hat</h3>
              <ul className="plan-buyers">
                {plan.buyers.slice(0, 6).map((b, i) => (
                  <li key={`${b.person}-${b.event_date}-${i}`}>
                    <b>{b.kind}</b> — {b.person}
                    {b.event_date && <> · Kauf {b.event_date}</>}
                    {b.reported_at && <> · gemeldet {b.reported_at}</>}
                  </li>
                ))}
              </ul>
              <p className="plan-sub">
                Meldungen laufen nach — ein Kongress-Kauf erscheint bis zu 45 Tage später.
              </p>
            </section>
          )}

          {plan.news.length > 0 && (
            <section className="plan-block">
              <h3>Schlagzeilen</h3>
              <ul className="plan-news">
                {plan.news.map((item) => (
                  <li key={item.headline}>
                    {item.de && <span className="plan-news-de">{item.de}</span>}
                    <span className="plan-news-orig">{item.headline}</span>
                  </li>
                ))}
              </ul>
              <p className="plan-sub">
                Deutsche Fassung maschinell übersetzt — sie erfindet gelegentlich Inhalt.
                Das Original steht darum immer darunter.
              </p>
            </section>
          )}
        </div>
      )}

      {!open && buyers && <p className="plan-stance-note">Gemeldete Käufe: {buyers}</p>}
    </li>
  );
}

export function KaufplanView({ onNavigate }: { onNavigate: (view: string) => void }) {
  const [plans, setPlans] = useState<BuyPlan[] | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState<PlanFilter>("alle");

  useEffect(() => {
    let ignore = false;
    fetchKaufplan(12)
      .then((r) => {
        if (ignore) return;
        setPlans(r.plans);
        setGeneratedAt(r.generated_at);
      })
      .catch(() => {
        if (!ignore) setFailed(true);
      });
    return () => {
      ignore = true;
    };
  }, []);

  if (failed) return <p className="brief-muted">Kaufpläne nicht erreichbar.</p>;
  if (plans === null) return <p className="brief-muted">lädt …</p>;

  const visible = filterPlans(plans, filter);
  const record = plans[0]?.track_record ?? null;
  const readyCount = plans.filter((p) => p.entry.stance === "kaufbereit").length;

  return (
    <section>
      <header className="section-head reveal">
        <p className="eyebrow">Kaufplan</p>
        <h1>Was du kaufen könntest — und zu welchem Preis</h1>
        <p className="section-sub">
          {readyCount === 0
            ? "Aktuell steht kein Titel im Stützbereich."
            : `${readyCount} von ${plans.length} Titeln stehen im Stützbereich.`}
          {generatedAt && ` Stand ${new Date(generatedAt).toLocaleString("de-DE")}.`}
        </p>
      </header>

      {/* Nur die volle Zeile des Backends: sie trägt Zahl UND Einordnung. Die kompakte
          Fassung (trackRecordLine) sagt dasselbe noch einmal und machte die Box doppelt so
          hoch — gemessen am 2026-08-27 im 390-px-Verify. Sie bleibt für die Telegram-
          Nachricht, wo es keinen Platz für den ganzen Satz gibt. */}
      {record && (
        <p className="plan-record">
          <b>Bilanz dieser Liste:</b> {record.line}
        </p>
      )}

      <div className="seg-switch" role="tablist" aria-label="Kaufplan-Filter">
        {PLAN_FILTERS.map((f) => (
          <button
            key={f.key}
            role="tab"
            aria-selected={filter === f.key}
            className={filter === f.key ? "seg-btn active" : "seg-btn"}
            onClick={() => setFilter(f.key)}
          >
            {f.label} ({filterPlans(plans, f.key).length})
          </button>
        ))}
      </div>

      {visible.length > 0 ? (
        <ul className="plan-list">
          {visible.map((plan) => (
            <PlanCard key={plan.ticker} plan={plan} />
          ))}
        </ul>
      ) : (
        <p className="brief-muted">{emptyNote(filter, plans.length)}</p>
      )}

      <p className="brief-muted">
        Der Kaufplan bündelt, was der Scout berechnet hat. Er ist keine Anlageberatung, und die
        Bilanz oben sagt, wie viel die bisherigen Vorschläge wert waren.
        <button className="stock-more" onClick={() => onNavigate("ergebnisse")}>
          Die ganze Auswertung →
        </button>
      </p>
    </section>
  );
}
