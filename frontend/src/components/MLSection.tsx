import { useState } from "react";

import { MLPanel } from "./MLPanel";
import { ResearchPanel } from "./ResearchPanel";

// The Machine-Learning top-level category: an explainer up top, then two sub-areas.
export function MLSection() {
  const [tab, setTab] = useState<"meta" | "research">("meta");

  return (
    <>
      <section className="ml-intro">
        <h1>Machine Learning</h1>
        <p>
          Das Modell hier ist <strong>kein Orakel</strong>, das Kurse vorhersagt. Es entscheidet etwas
          Bescheideneres und Ehrlicheres: <strong>ob man einem Handelssignal überhaupt folgen sollte</strong> —
          gemessen am Marktregime (Volatilität, Marktbreite, Drawdown-Zustand). Das ist die Methode des{" "}
          <em>Meta-Labeling</em> (López de Prado): Die Strategie liefert die Richtung, das Modell liefert
          die Konviktion.
        </p>
        <p>Diese Kategorie hat zwei Teile:</p>
        <ul className="ml-points">
          <li>
            <strong>Meta-Modell</strong> — ein einzelnes, festes Modell. Es zeigt, wie gut die
            „Soll ich folgen?"-Entscheidung out-of-sample funktioniert und welche Merkmale es gelernt hat.
          </li>
          <li>
            <strong>Auto-Research</strong> — ein Loop, der im Hintergrund <em>laufend neue
            Konfigurationen sucht</em> und sich so verbessert. Wichtig: Ein Modell wird <strong>nicht</strong>{" "}
            durch bloßes Wiederholen auf denselben Daten besser — das wäre Overfitting. Es wird besser, indem
            breiter gesucht wird, während die statistische Hürde (Deflated Sharpe Ratio) mit <em>jedem</em>{" "}
            Versuch steigt — so kann Zufall nicht überleben.
          </li>
        </ul>
        <p className="ml-honest">
          Alles wird per <strong>purged Walk-Forward</strong> validiert — jede Zahl ist out-of-sample und
          nach Kosten. Ehrliche Erwartung bei kostenlosen Tagesdaten: <strong>Risikoreduktion</strong>{" "}
          (kleinere Drawdowns, ruhigere Kurve), <strong>kein Alpha-Wunder</strong>. Es ist ein Forschungs-
          und Lern-Harness, keine Anlageberatung.
        </p>
      </section>

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
