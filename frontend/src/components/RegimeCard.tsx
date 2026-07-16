import { useEffect, useState } from "react";

import { fetchRegime, type Regime, type RegimeSignal } from "../api";
import { Disclosure } from "./ui/Disclosure";

function signalDot(signal: RegimeSignal): string {
  if (signal.green === null) return "⚪";
  return signal.green ? "🟢" : "🔴";
}

/** v8 market traffic light: one glance for the market, the four signals fold away. */
export function RegimeCard() {
  const [regime, setRegime] = useState<Regime | null>(null);

  useEffect(() => {
    // Silent absence on failure — the traffic light is context, never a blocker.
    fetchRegime()
      .then((r) => setRegime(r.regime))
      .catch(() => undefined);
  }, []);

  if (!regime || regime.level === "unknown") return null;

  return (
    <section className="panel regime reveal">
      <Disclosure
        summary={
          <>
            {regime.emoji} Marktlage: <strong>{regime.label}</strong>{" "}
            <span className="nobr">
              ({regime.green_count}/{regime.available} Signale grün)
            </span>
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
      </Disclosure>
    </section>
  );
}
