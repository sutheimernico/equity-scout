import { Disclosure } from "./ui/Disclosure";

// Aufklappbare Erklärung, wie die Scores zustande kommen — hält den Screen ehrlich und lesbar.
export function MethodologyNote() {
  return (
    <Disclosure summary="Wie werden die Aktien ausgewählt? (kurz erklärt)">
      <p>
        <strong>Kein KI-/ML-Modell.</strong> Die Auswahl ist ein regelbasierter Faktor-Funnel: Jede
        Aktie wird auf fünf Faktor-Gruppen bewertet — Value, Qualität, Momentum, Wachstum und geringe
        Volatilität — aus kostenlosen Fundamentaldaten und Kursen. Pro Kennzahl werden alle Aktien in
        einen Perzentil-Rang (0–100) einsortiert; Value, Qualität und Wachstum innerhalb der Branche,
        damit ein Tech-KGV nicht mit dem eines Versorgers verglichen wird. Jeder Risiko-Bucket gewichtet
        die Gruppen anders — klick eine Karte an für <em>Perzentil × Gewicht = Beitrag</em>; der Score
        ist die Summe der Beiträge. Negative KGVs werden verworfen, nicht als „billig" gewertet. Das ist
        ein Recherche-Screen, keine Anlageberatung — die Gewichte sind begründete Voreinstellungen,
        nicht backgetestet.
      </p>
    </Disclosure>
  );
}
