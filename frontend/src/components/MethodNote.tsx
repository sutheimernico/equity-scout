import { Disclosure } from "./ui/Disclosure";

// The one place that explains where the numbers come from (Nico 2026-08-07: "irgendwo
// auch mal so eine Infoseite hinterlegen, wie Du auf dein Potenzial kommst"). Rendered
// under every list that shows a Potenzial block or a score (Heute, Entscheiden, Radar)
// so the explanation is always one tap from the number it explains — and written ONCE,
// so the three surfaces can never drift apart.
export function MethodNote() {
  return (
    <Disclosure summary="Woher kommen diese Zahlen?">
      <div className="method-note">
        <p>
          <b>Potenzial (z.&nbsp;B. +16&nbsp;%)</b> — der Abstand vom aktuellen Kurs zum
          durchschnittlichen Kursziel der Bank-Analysten, die die Aktie beobachten
          (Quelle: yfinance-Konsens, meist auf ~12 Monate gedacht). „laut 34 Analysten“
          sagt, wie viele Schätzungen dahinterstehen — mehr Schätzungen, belastbarerer
          Durchschnitt. Das ist eine <b>Meinung Dritter</b>, kein Versprechen und nicht
          unsere Rechnung.
        </p>
        <p>
          <b>Einstiegs-Score und Einstiegszone</b> — <b>unser Modell</b>. Es bewertet nur
          den <b>Zeitpunkt</b>: Wie nah liegt der Kurs an seinen letzten Halte-Niveaus
          (Unterstützungen), wie ist die Bewertungslücke, wie das Momentum. Es sagt nie,
          was eine Aktie wert ist, und erzeugt keine Kursziele.
        </p>
        <p>
          <b>Signal-Filter</b> — ein lokal trainiertes ML-Modell, das dieselben Signale
          nachsortiert (0–100). Auch das ist eine Zeitpunkt-Einschätzung, keine Prognose.
        </p>
        <p>
          Beides kann sich widersprechen, ohne dass eines falsch ist: Analysten beziffern
          den <b>Wert</b>, unser Modell den <b>Zeitpunkt</b>. Keine Anlageberatung.
        </p>
      </div>
    </Disclosure>
  );
}
