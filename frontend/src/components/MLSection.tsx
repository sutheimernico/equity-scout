import { useState } from "react";

import { MLPanel } from "./MLPanel";
import { ResearchPanel } from "./ResearchPanel";
import { Disclosure } from "./ui/Disclosure";

// The Machine-Learning top-level category: a one-line orientation, the depth folded into a
// disclosure, then two sub-areas (the fixed meta-model and the continuous research loop).
export function MLSection() {
  const [tab, setTab] = useState<"meta" | "research">("meta");

  return (
    <>
      <header className="section-head">
        <p className="eyebrow">Machine Learning</p>
        <h1>Lohnt es sich, dem Signal zu folgen?</h1>
        <p className="section-sub">
          Das Modell sagt keine Kurse voraus. Es entscheidet das Bescheidenere und Ehrlichere:{" "}
          <strong>ob man einem Handelssignal überhaupt folgen sollte</strong> — gemessen am Marktregime
          (Volatilität, Marktbreite, Drawdown). Die Strategie liefert die Richtung, das Modell die Konviktion.
        </p>
      </header>

      <Disclosure summary="Wie funktioniert das? Meta-Labeling & der eingebaute Overfitting-Schutz">
        <p>
          Das ist die Methode des <em>Meta-Labeling</em> (López de Prado). Validiert wird per{" "}
          <strong>purged Walk-Forward</strong> — jede Zahl ist out-of-sample und nach Kosten.
        </p>
        <p>
          Die Kategorie hat zwei Teile: das <strong>Meta-Modell</strong> (ein einzelnes, festes Modell — wie
          gut die „Soll ich folgen?"-Entscheidung out-of-sample funktioniert) und <strong>Auto-Research</strong>{" "}
          (ein Loop, der im Hintergrund laufend neue Konfigurationen sucht).
        </p>
        <p>
          Ein Modell wird <strong>nicht</strong> durch bloßes Wiederholen auf denselben Daten besser — das
          wäre Overfitting. Es wird besser, indem breiter gesucht wird, während die statistische Hürde
          (Deflated Sharpe) mit <em>jedem</em> Versuch steigt — so kann Zufall nicht überleben.
        </p>
        <p>
          Ehrliche Erwartung bei kostenlosen Tagesdaten: <strong>Risikoreduktion</strong> (kleinere
          Drawdowns, ruhigere Kurve), <strong>kein Alpha-Wunder</strong>. Forschungs- und Lern-Harness,
          keine Anlageberatung.
        </p>
      </Disclosure>

      <div className="tabbar">
        <button className={tab === "meta" ? "tab active" : "tab"} onClick={() => setTab("meta")}>
          Meta-Modell
        </button>
        <button
          className={tab === "research" ? "tab active" : "tab"}
          onClick={() => setTab("research")}
        >
          Auto-Research
        </button>
      </div>

      {tab === "meta" ? <MLPanel /> : <ResearchPanel />}
    </>
  );
}
