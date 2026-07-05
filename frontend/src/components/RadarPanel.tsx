import { useEffect, useState } from "react";

import { fetchRadar, type RadarResponse, type WatchlistEntry } from "../api";
import { BUCKET_LABELS, pct, toPercent } from "../format";
import { Bar } from "./ui/Bar";
import { Chip } from "./ui/Chip";
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

function RadarEntry({ entry }: { entry: WatchlistEntry }) {
  const score = toPercent(entry.composite);
  const { bandLeft, bandWidth, priceLeft } = zoneGeometry(entry);

  return (
    <article className="panel radar-entry">
      <div className="radar-entry-head">
        <span className="ticker">{entry.ticker}</span>
        <span className="radar-name">{entry.name}</span>
        <Chip>{BUCKET_LABELS[entry.bucket] ?? entry.bucket}</Chip>
        <span className="radar-composite tnum">{score}</span>
      </div>

      <div className="radar-meter" role="img" aria-label={`Composite-Score ${score} von 100`}>
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

      <div className="zone-legend">
        <span className="nobr">
          Zone <span className="tnum">{entry.entry_zone_low}–{entry.entry_zone_high}</span>
        </span>
        <span className="nobr">
          Kurs <span className="tnum">{entry.price}</span>
        </span>
        <span className={entry.in_zone ? "nobr zone-prox in" : "nobr zone-prox"}>
          <span className="tnum">{pct(entry.proximity)}</span>
          {entry.in_zone ? " · in Zone" : ""}
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

      {/* Task 7 will formalize this as <DisclaimerBar/>; kept inline so the surface stays honest standalone. */}
      <p className="surface-disclaimer">{data.disclaimer}</p>
    </>
  );
}
