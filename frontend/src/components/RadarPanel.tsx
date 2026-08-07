import { useEffect, useState } from "react";

import { fetchRadar, type RadarResponse, type WatchlistEntry } from "../api";
import { shortCompanyName } from "../company";
import { BUCKET_LABELS, toPercent } from "../format";
import { MethodNote } from "./MethodNote";
import { PotentialBlock } from "./PotentialBlock";
import { SignalStackBlock } from "./SignalStackBlock";
import { StockLogo } from "./StockLogo";
import { Bar } from "./ui/Bar";
import { Chip } from "./ui/Chip";
import { DisclaimerBar } from "./ui/DisclaimerBar";
import { Disclosure } from "./ui/Disclosure";

// Radar sub-signal names → German labels (the three readings behind each composite score).
const READING_LABELS: Record<string, string> = {
  dip_quality: "Dip-Qualität",
  value_gap: "Bewertungslücke",
  momentum: "Momentum",
};

// ISO timestamp → compact "YYYY-MM-DD HH:MM" (backend emits tz-aware isoformat).
function formatStamp(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

// Project the zone [low, high] and the current price onto a 0–100 % axis. The domain is padded so
// the price tick stays visible even when the price sits outside the zone.
function zoneGeometry(entry: WatchlistEntry) {
  const { entry_zone_low: lo, entry_zone_high: hi, price } = entry;
  const min = Math.min(lo, price);
  const max = Math.max(hi, price);
  const pad = (max - min || 1) * 0.12;
  const dMin = min - pad;
  const span = max + pad - dMin || 1;
  const at = (v: number) => Math.max(0, Math.min(100, ((v - dMin) / span) * 100));
  return { bandLeft: at(lo), bandWidth: at(hi) - at(lo), priceLeft: at(price) };
}

/** Today's entry state as the same chip the Heute list and the inbox use — the one
 *  visual language for "is this a good moment" across the app. */
function zoneChipLabel(entry: WatchlistEntry): string {
  if (entry.in_zone) return "✓ Einstiegsbereich";
  if (entry.price < entry.entry_zone_low) return "⚠ unter der Zone — Support gebrochen";
  return `⚠ ${Math.round(entry.proximity * 100)} % über der Einstiegszone`;
}

function RadarEntry({ entry }: { entry: WatchlistEntry }) {
  const score = toPercent(entry.composite);
  const { bandLeft, bandWidth, priceLeft } = zoneGeometry(entry);

  return (
    <article className="panel radar-entry">
      {/* Same head as the inbox card (company first, ticker small, today's zone chip,
          analyst potential right) — the ticker-first head broke mid-word at 390 px
          ("ITC.N S") and carried no company name a lay reader could recognise. */}
      <div className="pitch-head">
        <StockLogo ticker={entry.ticker} name={entry.name} />
        <span className="pitch-ident">
          <span className="pitch-company">{shortCompanyName(entry.name)}</span>
          <span className="ticker">{entry.ticker}</span>
          <span
            className={entry.in_zone ? "brief-chip brief-chip-good" : "brief-chip brief-chip-warn"}
          >
            {zoneChipLabel(entry)}
          </span>
        </span>
        <PotentialBlock
          upsidePct={entry.analyst_upside_pct ?? null}
          analystCount={entry.analyst_count ?? null}
        />
      </div>

      <div className="radar-chips">
        <Chip>{BUCKET_LABELS[entry.bucket] ?? entry.bucket}</Chip>
        {entry.ml && (
          <Chip>
            Signal-Filter {entry.ml.score}/100 · Stand {entry.ml.created_at.slice(0, 10)}
          </Chip>
        )}
      </div>

      {/* Labelled and attributed: a bare blue "71" read as anything from a price to a
          percent. Same attribution split as the Heute list — this number is OUR model. */}
      <p className="radar-score-label">
        Einstiegs-Score <b className="tnum">{score}/100</b> — unser Modell, bewertet nur den
        Zeitpunkt
      </p>
      <div className="radar-meter" role="img" aria-label={`Einstiegs-Score ${score} von 100`}>
        <Bar value={entry.composite} max={1} />
      </div>

      <div
        className="zone-track"
        role="img"
        aria-label={
          `Einstiegszone ${entry.entry_zone_low}–${entry.entry_zone_high}, ` +
          `Kurs ${entry.price}${entry.in_zone ? ", in der Zone" : ""}`
        }
      >
        <div className="zone-rail">
          <div
            className={entry.in_zone ? "zone-band in-zone" : "zone-band"}
            style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }}
          />
        </div>
        <div
          className={entry.in_zone ? "zone-price in" : "zone-price"}
          style={{ left: `${priceLeft}%` }}
        />
      </div>

      {/* The raw signed proximity ("-10.5 % · in Zone") moved into the head chip in
          plain words — a negative percent next to "in Zone" was a riddle, not a fact. */}
      <div className="zone-legend">
        <span className="nobr">
          Zone <span className="tnum">{entry.entry_zone_low}–{entry.entry_zone_high}</span>
        </span>
        <span className="nobr">
          Kurs <span className="tnum">{entry.price}</span>
        </span>
      </div>
      {entry.zone_note && <p className="zone-note">{entry.zone_note}</p>}

      <Disclosure summary="Signale">
        <div className="radar-readings">
          {entry.readings.map((r) => (
            <div className="radar-reading" key={r.name}>
              <span className="radar-reading-label">{READING_LABELS[r.name] ?? r.name}</span>
              <span className="radar-reading-score tnum">{toPercent(r.score)}</span>
              <p className="radar-reading-reason">{r.reason}</p>
            </div>
          ))}
        </div>
        <SignalStackBlock ticker={entry.ticker} />
      </Disclosure>
    </article>
  );
}

export function RadarPanel() {
  const [data, setData] = useState<RadarResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // `ignore` guards against a setState after the effect is torn down (unmount / refire).
    let ignore = false;
    fetchRadar()
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

  const wl = data.watchlist;
  if (!wl) {
    return (
      <>
        <header className="section-head reveal">
          <p className="eyebrow">Radar</p>
          <h1>Watchlist</h1>
        </header>
        <p className="state">
          Noch keine Watchlist — <code>run_radar.py</code> ausführen.
        </p>
      </>
    );
  }

  const skipped = Object.entries(wl.skipped);

  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Radar</p>
        <h1>Watchlist — Einstiegszonen im Blick</h1>
        <p className="section-sub">
          {wl.entries.length} Titel · Stand {formatStamp(wl.created_at)}. Sortiert nach
          Composite-Score. Keine Kaufsignale, keine Anlageberatung.
        </p>
      </header>

      <div className="radar-grid">
        {wl.entries.map((entry) => (
          <RadarEntry key={entry.ticker} entry={entry} />
        ))}
      </div>

      {skipped.length > 0 && (
        <div className="radar-skipped">
          {skipped.map(([ticker, reason]) => (
            <p className="radar-skipped-row" key={ticker}>
              übersprungen: <span className="ticker">{ticker}</span> — {reason}
            </p>
          ))}
        </div>
      )}

      <MethodNote />
      <DisclaimerBar text={data.disclaimer} />
    </>
  );
}
