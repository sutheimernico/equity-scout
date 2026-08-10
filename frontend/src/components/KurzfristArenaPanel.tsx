import { useEffect, useState } from "react";

import { fetchShortterm, type ShortTermLane, type ShortTermResponse } from "../api";
import { num, pct } from "../format";
import { Chip } from "./ui/Chip";
import { Explain } from "./ui/Explain";

const LANE_LABEL: Record<string, string> = {
  swing: "Event-Swing (1–5 Tage)",
  session: "Intraday-Session (ORB)",
  crypto: "Crypto-Daytrader (Donchian)",
};

const LANE_NOTE: Record<string, string> = {
  swing: "Kauft bullishe Earnings-Events zum Schlusskurs, Ziel +5 % / Stop −3 % / max. ~5 Handelstage.",
  session:
    "Opening-Range-Breakout auf ~15 Min. VERZÖGERTEN Kursen (Settled-Bar-Modell), nie über Nacht.",
  crypto: "Donchian-20-Ausbruch auf Kraken-ECHTZEIT-Bars, 24/7 — Benchmark ist BTC halten, nicht Cash.",
};

// v12 I4: the evidence checklist — when does this lane earn real depot capital?
function PromotionLine({ lane }: { lane: ShortTermLane }) {
  const promo = lane.promotion;
  if (lane.promoted) {
    return (
      <Explain tone="hint">
        🎓 <b>Im Auto-Depot</b> — diese Lane hat den Prüfstand bestanden und verdient
        Depot-Kapital. Degradierung, sobald das 60-Tage-Netto-P&L negativ wird.
      </Explain>
    );
  }
  if (!promo) return null;
  const pf = promo.profit_factor_unbounded
    ? "∞"
    : promo.profit_factor === null
      ? "—"
      : promo.profit_factor.toFixed(2);
  return (
    <Explain tone="hint">
      Prüfstand: {promo.realized_trades}/30 Trades · {promo.days_active}/60 Tage · PF {pf}
      {promo.eligible
        ? " — ✅ bestanden, Aufnahme beim nächsten Nightly-Lauf"
        : promo.missing.length > 0
          ? ` — offen: ${promo.missing.join(", ")}`
          : ""}
    </Explain>
  );
}

/** The measurement method changed mid-track on 2026-08-06 — saying nothing would make the
 *  earlier, simulated part of the curve look like the same thing as the later, real part. */
function RegimeNote({ lane }: { lane: ShortTermLane }) {
  if (!lane.execution_regime) return null;
  const since = new Date(lane.execution_regime).toLocaleDateString("de-DE");
  return (
    <Explain tone="hint">
      Echte Broker-Fills (Alpaca Paper) seit dem {since}. Davor: simulierte Fills auf
      verzögerten Kursen — der frühere Verlauf ist dadurch zu günstig und darf nicht als
      derselbe Track gelesen werden.
    </Explain>
  );
}

/** Where does the result come from? The headline number hides its own cause: on 2026-08-10 the
 *  session lane's −233 read as a failing strategy, while 74 % of it was five one-off cleanup
 *  flats and the actual ORB rules were at −56. Biggest contributor first. */
function LossAnatomy({ lane }: { lane: ShortTermLane }) {
  const rows = lane.loss_anatomy ?? [];
  if (rows.length === 0) return null;
  return (
    <>
      <h4 style={{ marginTop: "var(--space-4)" }}>Woher das Ergebnis kommt</h4>
      <table className="history">
        <thead>
          <tr>
            <th>Grund für den Ausstieg</th>
            <th className="num">Trades</th>
            <th className="num">Summe</th>
            <th className="num">Ø</th>
            <th className="num">Treffer</th>
            <th className="num">Anteil</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.reason}>
              <td>{r.reason}</td>
              <td className="num">{r.n}</td>
              <td className="num">{num(r.total, 2)}</td>
              <td className="num">{num(r.avg, 2)}</td>
              <td className="num">
                {r.wins}/{r.n}
              </td>
              <td className="num">
                {r.share_of_total === null ? "—" : pct(r.share_of_total, 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Explain tone="hint">
        „Anteil" ist der Beitrag zum Gesamtergebnis. Ein negativer Anteil bedeutet, dass diese
        Gruppe gegen das Gesamtergebnis lief — bei einem Verlustbuch also ein Gewinnbeitrag.
        Bei einem Ergebnis nahe Null steht „—", weil ein Anteil von fast Nichts kein Maß ist.
      </Explain>
    </>
  );
}

/** Is this book's result a verdict yet, or still noise? Measured 2026-08-10: the session lane
 *  sat at −2.4 % over 48 trades with p=0.169 — that is "we do not know", not "it is bad", and
 *  the difference decides whether you keep going or stop. Crypto's −14.11 average, by
 *  contrast, IS significant. Tone follows the finding, not the sign of the return. */
function SignificanceNote({ lane }: { lane: ShortTermLane }) {
  const s = lane.significance;
  if (!s || s.verdict === "zu wenige Trades") {
    return (
      <Explain tone="hint">
        Aussagekraft: noch zu wenige abgeschlossene Trades ({s?.n ?? 0}) — jede Zahl hier ist
        bis dahin Rauschen.
      </Explain>
    );
  }
  // "info" for a result that has actually resolved, "hint" while it is still a maybe.
  return (
    <Explain tone={s.significant ? "info" : "hint"}>
      <b>Aussagekraft: {s.verdict}.</b> {s.note}
      {!s.significant && s.trades_missing ? (
        <>
          {" "}
          Bis dahin ist das Ergebnis <b>kein Urteil über die Strategie</b> — nur eine noch zu
          kurze Messreihe.
        </>
      ) : null}
    </Explain>
  );
}

/** The crypto lane's strategy changed timescale on 2026-08-10; the curve before that is a
 *  different system, not an earlier part of this one. */
function StrategyRegimeNote({ lane }: { lane: ShortTermLane }) {
  if (!lane.strategy_regime) return null;
  const since = new Date(lane.strategy_regime).toLocaleDateString("de-DE");
  return (
    <Explain tone="hint">
      Strategie-Umstellung am {since}: Donchian-Kanal jetzt auf Tagesbars statt
      15-Minuten-Bars. Grund war die Reibung — rund 180 Basispunkte pro Roundtrip (Kraken
      nimmt 0,80 % Taker je Seite) waren auf der kurzen Zeitskala größer als die erwartete
      Bewegung. Der Verlauf davor gehört zu einer anderen Strategie und ist kein Vorlauf
      dieser.
    </Explain>
  );
}

/** The book and the broker account report the same trades on different denominators — the
 *  strategy ledger runs on 10k, the paper account holds 100k. Showing only the book's
 *  percentage next to a live account overstates that account's return ~10x. */
function AccountNote({ lane }: { lane: ShortTermLane }) {
  if (lane.broker_equity === null) return null;
  const usage = lane.broker_equity > 0 ? lane.equity / lane.broker_equity : null;
  return (
    <Explain tone="hint">
      Konto bei Alpaca: {num(lane.broker_equity, 0)} USD. Die Rendite in dieser Tabelle
      rechnet auf das Strategie-Buch ({num(lane.initial_capital, 0)} USD Startkapital) — auf
      den vollen Kontorahmen bezogen ist sie entsprechend kleiner
      {usage !== null ? ` (eingesetzt: ${pct(usage, 0)} des Kontos)` : ""}.
    </Explain>
  );
}

function LaneCard({ lane }: { lane: ShortTermLane }) {
  const lead =
    lane.benchmark_return !== null ? lane.total_return - lane.benchmark_return : null;
  return (
    <section className="strat-block">
      <div className="chip-row" style={{ marginBottom: "var(--space-3)" }}>
        <Chip>
          <b>{LANE_LABEL[lane.lane] ?? lane.lane}</b>
        </Chip>
        <Chip>Equity {num(lane.equity, 0)}</Chip>
        <Chip>{lane.open_positions.length} offen</Chip>
      </div>
      <Explain tone="hint">{LANE_NOTE[lane.lane]}</Explain>
      <RegimeNote lane={lane} />
      <StrategyRegimeNote lane={lane} />
      <AccountNote lane={lane} />
      <SignificanceNote lane={lane} />
      <PromotionLine lane={lane} />

      <table className="history">
        <thead>
          <tr>
            <th>Rendite</th>
            <th>Benchmark ({lane.benchmark_ticker})</th>
            <th>Vorsprung</th>
            <th>Max. Drawdown</th>
            <th>Trades</th>
            <th>Trefferquote</th>
            <th>Kosten</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{pct(lane.total_return)}</td>
            <td>{lane.benchmark_return === null ? "—" : pct(lane.benchmark_return)}</td>
            <td>{lead === null ? "—" : pct(lead)}</td>
            <td>{pct(lane.max_drawdown)}</td>
            <td>{lane.stats.n_trades}</td>
            <td>{lane.stats.win_rate === null ? "—" : pct(lane.stats.win_rate, 0)}</td>
            <td>{num(lane.stats.fees_paid, 2)}</td>
          </tr>
        </tbody>
      </table>

      {lane.open_positions.length > 0 && (
        <p>
          Offen:{" "}
          {lane.open_positions
            .map((p) => `${p.ticker} (${num(p.qty, 4)} @ ${num(p.entry_price, 2)})`)
            .join(" · ")}
        </p>
      )}
      <LossAnatomy lane={lane} />
      {lane.recent_trades.length > 0 && (
        <details>
          <summary>Letzte Trades ({lane.recent_trades.length})</summary>
          <table className="history">
            <thead>
              <tr>
                <th>Zeit</th>
                <th>Trade</th>
                <th>Preis</th>
                <th>Grund</th>
                <th>P&L</th>
              </tr>
            </thead>
            <tbody>
              {lane.recent_trades.map((t, i) => (
                <tr key={`${t.executed_at}-${t.ticker}-${t.side}-${i}`}>
                  <td>{t.executed_at.slice(0, 16).replace("T", " ")}</td>
                  <td>
                    {t.side === "buy" ? "↑" : "↓"} {t.ticker}
                  </td>
                  <td>{num(t.price, 2)}</td>
                  <td>{t.reason}</td>
                  <td>{t.realized_pnl === null ? "—" : num(t.realized_pnl, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </section>
  );
}

export function KurzfristArenaPanel() {
  const [data, setData] = useState<ShortTermResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchShortterm()
      .then(setData)
      .catch((e: unknown) => setError(String(e)));
  }, []);

  if (error) return <p className="state err">Fehler: {error}</p>;
  if (!data) return <p className="state">Lädt…</p>;

  return (
    <>
      <Explain>
        Drei Kurzfrist-Ansätze treten mit je 10.000 USD Spielgeld gegeneinander an — die Arena{" "}
        <strong>misst</strong>, welcher seine Kosten überlebt. Ehrliche Erwartung aus der
        Forschung: Kurzfrist-Trading verliert im Retail-Rahmen nach Kosten meistens. Alle Lanes
        long-only, alle Fills mit Slippage; die Session-Lane rechnet zusätzlich mit einem
        Verzögerungs-Modell für die ~15 Min. alten Gratis-Kurse.
      </Explain>

      {!data.available || data.lanes.length === 0 ? (
        <section className="strat-block">
          <h3 className="block-title">Noch keine Lane gestartet</h3>
          <Explain tone="hint">
            Die Lanes starten mit ihren Cron-Läufen (crypto: alle 15 Min.; session: im
            US-Marktfenster; swing: nächtlich) — oder per Hand:
          </Explain>
          <p>
            <code>uv run python scripts/run_shortterm.py --lane crypto</code>
          </p>
        </section>
      ) : (
        data.lanes.map((lane) => <LaneCard key={lane.lane} lane={lane} />)
      )}

      <p className="state">{data.disclaimer}</p>
    </>
  );
}
