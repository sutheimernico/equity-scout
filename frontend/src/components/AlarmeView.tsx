import { OpportunityList } from "./OpportunityList";
import { PushSetup } from "./PushSetup";

// "Benachrichtigungen": what the app tells you, when, and how to switch it on.
// Written for someone who does not follow markets — every rule is a sentence, not a
// threshold.
export function AlarmeView({ onOpenStock }: { onOpenStock?: (ticker: string) => void }) {
  return (
    <>
      <header className="section-head reveal">
        <p className="eyebrow">Benachrichtigungen</p>
        <h1>Was dir das Handy meldet</h1>
        <p className="section-sub">
          Du musst die App nicht öffnen, um nichts zu verpassen. Sie meldet sich von
          selbst — und zwar nur, wenn es etwas zu sagen gibt.
        </p>
      </header>

      <section className="strat-block reveal">
        <h3 className="block-title">Zuletzt gemeldet</h3>
        <OpportunityList onOpenStock={onOpenStock} />
      </section>

      <PushSetup />

      <section className="strat-block reveal">
        <h3 className="block-title">Wann du eine Meldung bekommst</h3>
        <dl className="brief-detail">
          <dt>Chance des Tages</dt>
          <dd>
            Wenn ein Titel gleichzeitig günstig bewertet ist, in seiner Kaufzone liegt und
            die Qualitätsschwelle schafft. Höchstens einmal pro Titel pro Woche.
          </dd>
          <dt>Etwas ist passiert</dt>
          <dd>
            Wenn mehrere unabhängige Käufer (Politiker, Insider, große Fonds) im selben
            Titel auftauchen — oder ein Titel plötzlich ungewöhnlich stark bewegt wird.
          </dd>
          <dt>Dein Depot</dt>
          <dd>
            Wenn der Autopilot etwas gekauft oder verkauft hat, das du wissen solltest.
          </dd>
          <dt>Etwas ist kaputt</dt>
          <dd>
            Wenn eine Kette seit Stunden nicht gelaufen ist. Lieber eine Störmeldung als
            der falsche Eindruck, es sei nichts los.
          </dd>
        </dl>
        <p className="muted">
          Was du <b>nicht</b> bekommst: „Kaufsignale“, Kursziele oder Versprechen. Jede
          Meldung sagt dir, was gemessen wurde — die Entscheidung bleibt bei dir.
        </p>
      </section>

      <section className="strat-block reveal">
        <h3 className="block-title">Warum drei Kanäle?</h3>
        <p className="muted">
          <b>App-Nachricht</b> ist der Hauptweg: die Meldung kommt von dieser App, direkt
          auf den Sperrbildschirm. <b>ntfy</b> ist die Reserve — sie braucht keine
          Installation dieser App und funktioniert auch, wenn du sie mal löschst.{" "}
          <b>Telegram</b> bleibt für die lange Fassung mit Chart und Knöpfen.
        </p>
        <p className="muted">
          Alle drei laufen über deinen eigenen Rechner. Läuft er nicht, kommt nichts an —
          deshalb meldet sich die App auch, wenn sie selbst zu lange still war.
        </p>
      </section>
    </>
  );
}
