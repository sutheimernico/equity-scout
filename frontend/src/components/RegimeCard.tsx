import { useEffect, useState } from "react";

import {
  fetchRegime,
  type MarketBehaviour,
  type Regime,
  type RegimeSignal,
} from "../api";
import { Disclosure } from "./ui/Disclosure";

function signalDot(signal: RegimeSignal): string {
  if (signal.green === null) return "⚪";
  return signal.green ? "🟢" : "🔴";
}

/** Plain-German headline per level. The server's `label` ("Risk-on") stays visible as the
 * quoted jargon term — Telegram messages and finance news use it, so it must remain
 * findable — but it is no longer the thing a reader has to decode (Nico 2026-08-06,
 * round two: "Marktlage risk on, ich check das nicht. Also wofür ist das da?").
 */
const HEADLINE: Record<string, string> = {
  green: "Der Markt trägt gerade",
  yellow: "Der Markt ist gemischt",
  red: "Der Markt ist unter Druck",
};

/** What the state means in one plain sentence per level.
 *
 * Nico 2026-08-06: "diese Marktlage risk on, ich check gar nicht, was Du damit willst.
 * Also ist halt einfach alles grün, check ich nicht." The label was jargon plus a score
 * (4/4) with no statement of consequence — and it sat at the TOP of the phone screen, the
 * most prominent slot, for the least actionable fact. Each line says what the state does
 * and does not imply; none of them tells anyone to buy or sell.
 */
const MEANING: Record<string, string> = {
  green:
    "Rücksetzer einzelner Aktien sind in so einer Lage eher titelspezifisch als Marktstress — kein Kaufsignal, nur Kontext.",
  yellow:
    "Gemischtes Bild: ein Teil der Marktsignale ist gedreht. Einzeltitel reagieren in so einer Lage stärker auf schlechte Nachrichten.",
  red: "Der breite Markt ist unter Druck. Auch fundamental gute Titel fallen dann mit — der Autotrader drosselt in dieser Lage über sein Regime-Gate.",
};

/** WHO is trading, next to the traffic light's HOW the market stands (v17).
 *
 *  Nico's question: "wann kaufen Menschen Aktien und wann nicht?" Price alone cannot answer
 *  that — volume says how many people acted and therefore how much conviction stood behind a
 *  level. Every number is relative to that ticker's OWN normal day, because absolute volume
 *  compares nothing across asset classes.
 */
function BehaviourBlock({ behaviour }: { behaviour: MarketBehaviour | null }) {
  if (!behaviour?.available || behaviour.readings.length === 0) return null;
  const scored = behaviour.readings.filter((r) => r.ratio !== null);
  return (
    <>
      <h4>Wer handelt gerade — und wie viel</h4>
      <p>{behaviour.summary}</p>
      <ul className="regime-signals">
        {scored.map((r) => (
          <li key={r.ticker}>
            {r.is_capitulation ? "🔻" : r.is_spike ? "🔥" : "▫️"} <strong>{r.ticker}</strong> —{" "}
            {r.ratio!.toFixed(1)}× normales Volumen
            {r.obv_trend !== null && (
              <>
                , Kaufdruck {r.obv_trend > 0 ? "+" : ""}
                {r.obv_trend.toFixed(1)}
              </>
            )}
          </li>
        ))}
      </ul>
      <p className="regime-note">
        „Kaufdruck" ist das On-Balance-Volume der letzten 20 Tage, gemessen in normalen
        Handelstagen: +3 heißt, es wurde netto so viel gekauft wie an drei Durchschnittstagen.
        {" "}
        {behaviour.caveat}
      </p>
    </>
  );
}

/** v8 market traffic light: one glance for the market, the four signals fold away. */
export function RegimeCard() {
  const [regime, setRegime] = useState<Regime | null>(null);
  const [behaviour, setBehaviour] = useState<MarketBehaviour | null>(null);

  useEffect(() => {
    // Silent absence on failure — the traffic light is context, never a blocker.
    fetchRegime()
      .then((r) => {
        setRegime(r.regime);
        setBehaviour(r.behaviour ?? null);
      })
      .catch(() => undefined);
  }, []);

  if (!regime || regime.level === "unknown") return null;

  return (
    <section className="panel regime reveal">
      <Disclosure
        summary={
          <>
            {regime.emoji} Marktlage: <strong>{HEADLINE[regime.level] ?? regime.label}</strong>{" "}
            <span className="nobr">
              ({regime.green_count}/{regime.available} Signale grün · Fachwort „{regime.label}“)
            </span>
            {MEANING[regime.level] && (
              <span className="regime-meaning">{MEANING[regime.level]}</span>
            )}
          </>
        }
      >
        <ul className="regime-signals">
          {regime.signals.map((signal) => (
            <li key={signal.key}>
              {signalDot(signal)} <strong>{signal.label}</strong> — {signal.note}
            </li>
          ))}
        </ul>
        <p className="regime-note">
          Vier einfache, robuste Signale — eine Beschreibung der Marktlage, kein Timing-Signal
          und keine Anlageberatung.
        </p>
        <BehaviourBlock behaviour={behaviour} />
      </Disclosure>
    </section>
  );
}
