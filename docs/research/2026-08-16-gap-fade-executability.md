# Gap-Fade, Ausführbarkeit: der Effekt ist nach 15 Minuten weg (2026-08-16)

T8 aus `plans/2026-08-16-short-term-lane-expansion.md` — die Vorbedingung, an der die einzige
positiv getestete Idee dieser Serie hing. Der Backtest kauft zum offiziellen Eröffnungskurs,
den man in dem Moment, in dem die Lücke sichtbar wird, nicht mehr bekommt. Also dieselbe
Rechnung mit realistischen Einstiegszeitpunkten.

**Ergebnis: keine Lane.** Der Vorsprung zerfällt monoton und ist nach einer Viertelstunde
vollständig verschwunden.

## Die Messung

5-Minuten-Bars, 42 Handelstage (16.06.–14.08.2026), 283 Abwärtslücken ≤ −2 % über 68 Titel.
Gehalten wird jeweils bis zum Schluss desselben Tages.

| Einstieg | Rendite bis Schluss | t | Trefferquote |
|---|---|---|---|
| Eröffnungskurs (der Backtest) | +65,59 bp | 1,64 | 50,2 % |
| +5 Minuten | +29,97 bp | 0,81 | 48,1 % |
| **+15 Minuten** | **−0,09 bp** | **0,00** | 43,5 % |
| +30 Minuten | −34,68 bp | −1,18 | 42,8 % |

Rendite und Trefferquote fallen beide monoton. Nach einer Viertelstunde ist der Effekt exakt
null, nach einer halben Stunde negativ.

## Was das über den Befund von T7 sagt

Der große Backtest (324.931 Tage, t bis 15,69) war nicht falsch — der Gap-Fade **existiert**,
gemessen vom Eröffnungskurs aus. Er ist nur nicht **unserer**: Er lebt in den ersten Minuten
nach der Auktion, und in dieser Zeitspanne ist er für jemanden, der das Signal aus dem
Eröffnungskurs selbst ableitet, per Konstruktion unerreichbar.

Ehrlichkeitsgrenze dieser Prüfung: 283 Ereignisse aus 42 Tagen sind eine kleine Stichprobe, die
Standardfehler sind entsprechend groß — selbst der Eröffnungs-Einstieg erreicht hier nur
t = 1,64, wo der Langzeit-Backtest t = 15,69 zeigt. Belastbar ist deshalb nicht die einzelne
Zahl, sondern die **Monotonie**: vier Einstiegszeitpunkte, vier fallende Werte, in Rendite und
Trefferquote gleichzeitig.

## Der einzige verbleibende Weg — eine Entscheidung, kein Backtest

Professionelle Gap-Händler lösen das Timing-Problem über den **vorbörslichen Handel**: Die
Lücke lässt sich vor der Eröffnung aus dem Pre-Market-Kurs schätzen, und eine
Market-on-Open-Order bekommt dann den offiziellen Eröffnungskurs — genau den Preis, zu dem der
Effekt existiert. Alpaca unterstützt MOO-Orders, vorbörsliche Kurse liefern sowohl yfinance als
auch Alpaca.

Das wäre kein weiterer Backtest, sondern eine neue Baustelle mit eigenen Fragen: Wie gut sagt
der Pre-Market-Kurs die tatsächliche Lücke vorher? Wie liquide ist er bei den Titeln, um die es
geht? Und eine MOO-Order ist eine Order ohne Preisgrenze in die volatilste Auktion des Tages.
**Das ist Nicos Entscheidung, nicht die des Plans** — deshalb steht es unter „Offene Punkte",
nicht als nächste Aufgabe.
