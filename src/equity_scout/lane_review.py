"""Nightly review per lane: what happened, where it came from, and whether it means anything.

Nico's picture (2026-08-16): "Einmal am Abend läuft ein Lauf, wo alle gecheckt werden — wann
waren die erfolgreich, warum waren die erfolgreich, warum nicht, und daraus lernt es dann."

The pieces existed and were never wired together: `shortterm_book.loss_anatomy` answers WHERE
a result comes from but only runs when someone opens the page, and `significance.assess_trades`
answers whether it means anything but is read per lane in the UI. Neither is archived, so
nobody can say what changed since last week — which is the one thing a learning loop needs.

WHAT THIS IS NOT: a cause. Grouping realised P&L by exit reason is a decomposition, not an
explanation — "the loss sits in the stop-outs" says where the money went, never why the entries
were wrong. The review says so in its own text rather than letting the reader supply the
stronger claim for free.

Read-only over the book. Nothing here changes a rule, and nothing here promotes anything.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from equity_scout.shortterm_book import loss_anatomy
from equity_scout.significance import assess_trades


@dataclass(frozen=True)
class LaneReview:
    lane: str
    n_closed: int
    net: float
    verdict: str
    significant: bool
    trades_missing: int | None
    why: list[dict] = field(default_factory=list)
    delta_trades: int | None = None
    delta_net: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _closed(trades: list) -> list[float]:
    out = []
    for trade in trades:
        pnl = trade.get("realized_pnl") if isinstance(trade, dict) else getattr(trade, "realized_pnl", None)
        side = trade.get("side") if isinstance(trade, dict) else getattr(trade, "side", None)
        if side == "sell" and pnl is not None:
            out.append(float(pnl))
    return out


def review_lane(lane: str, trades: list, *, previous: LaneReview | dict | None = None) -> LaneReview:
    """One lane's night: result, decomposition, verdict, and the move since the last review."""
    pnls = _closed(trades)
    net = sum(pnls)
    assessment = assess_trades(pnls)
    why = loss_anatomy(trades)

    prev_trades = _prev(previous, "n_closed")
    prev_net = _prev(previous, "net")
    delta_trades = len(pnls) - prev_trades if prev_trades is not None else None
    delta_net = net - prev_net if prev_net is not None else None

    notes: list[str] = []
    if delta_trades == 0:
        notes.append("Seit der letzten Auswertung kein abgeschlossener Trade — nichts Neues zu lernen.")
    if why:
        top = why[0]
        share = top.get("share_of_total")
        if share is not None and abs(share) >= 0.5:
            notes.append(
                f"{abs(share) * 100:.0f} % des Ergebnisses stammen aus einer einzigen Gruppe: "
                f"„{top['reason']}\" ({top['n']} Trades). Das sagt, WO das Ergebnis herkommt, "
                f"nicht warum die Einstiege richtig oder falsch waren."
            )
    if assessment.is_significant:
        notes.append(
            f"Das Ergebnis ist statistisch entschieden ({assessment.verdict}) — weitere Trades "
            f"ändern daran nichts mehr, eine Entscheidung schon."
        )
    elif assessment.trades_missing:
        notes.append(
            f"Noch kein Urteil: es fehlen {assessment.trades_missing} Trades. Bis dahin ist die "
            f"Zahl eine Messreihe, kein Befund über die Strategie."
        )
    return LaneReview(
        lane=lane,
        n_closed=len(pnls),
        net=net,
        verdict=assessment.verdict,
        significant=assessment.is_significant,
        trades_missing=assessment.trades_missing,
        why=why,
        delta_trades=delta_trades,
        delta_net=delta_net,
        notes=notes,
    )


def _prev(previous: LaneReview | dict | None, key: str):
    if previous is None:
        return None
    if isinstance(previous, dict):
        return previous.get(key)
    return getattr(previous, key, None)


def render(reviews: list[LaneReview]) -> str:
    """The nightly text. Plain German, worst first — the lane that needs a decision leads."""
    if not reviews:
        return "Lane-Auswertung: keine Lane mit abgeschlossenen Trades."
    lines = ["Lane-Auswertung der Nacht:"]
    for review in sorted(reviews, key=lambda r: (not r.significant, r.net)):
        head = f"• {review.lane}: {review.n_closed} Trades, netto {review.net:+.2f} USD"
        if review.delta_net is not None and review.delta_trades:
            head += f" (seit letzter Auswertung {review.delta_trades:+d} Trades, {review.delta_net:+.2f} USD)"
        lines.append(head)
        for note in review.notes:
            lines.append(f"    {note}")
    return "\n".join(lines)
