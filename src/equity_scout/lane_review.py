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


# Measurement epochs: a lane whose MECHANICS changed mid-track must not have its verdict
# computed across the break (the champion-artifact lesson: a number measured on a sample the
# rule no longer generates). The crypto lane moved from 15-minute to daily bars on 2026-08-10
# (commit c446017); its 15-minute-era trades are evidence about a retired rule. The full
# curve stays visible on every surface — only the VERDICT window starts at the epoch.
# Accepted edge: a position OPENED under the old regime but CLOSED after the epoch counts into
# the new window (trade rows carry the close timestamp). That is one transition trade at most,
# and naming it here is cheaper than plumbing open timestamps through the review.
MEASUREMENT_EPOCHS: dict[str, str] = {"crypto": "2026-08-10"}


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
    # The verdict window this review was measured in (MEASUREMENT_EPOCHS); None = full history.
    # Persisted with the review so the next night can tell whether a comparison is even valid.
    epoch: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _field(trade, name: str):
    """Trades reach this module as dicts (storage) or as row objects (callers) — read both."""
    return trade.get(name) if isinstance(trade, dict) else getattr(trade, name, None)


def _closed(trades: list) -> list[float]:
    out = []
    for trade in trades:
        pnl = _field(trade, "realized_pnl")
        side = _field(trade, "side")
        if side == "sell" and pnl is not None:
            out.append(float(pnl))
    return out


def review_lane(
    lane: str,
    trades: list,
    *,
    previous: LaneReview | dict | None = None,
    rejections: list[dict] | None = None,
) -> LaneReview:
    """One lane's night: result, decomposition, verdict, and the move since the last review.

    `rejections` are the RESOLVED no-trade-book rows for this lane (rejection_review) —
    they answer Nico's question "hätten die verworfenen Signale funktioniert?" right where
    the traded result is judged."""
    epoch = MEASUREMENT_EPOCHS.get(lane)
    if epoch is not None:
        # A row without a timestamp stays in: live rows always carry `executed_at`
        # (st_trades.executed_at is NOT NULL), so dropping the undated ones would only
        # shrink the book silently in callers that build trades by hand.
        trades = [t for t in trades if str(_field(t, "executed_at") or epoch) >= epoch]
    pnls = _closed(trades)
    net = sum(pnls)
    assessment = assess_trades(pnls)
    why = loss_anatomy(trades)

    # A review measured in a DIFFERENT window is not comparable: the first crypto review
    # after the epoch shrank from 32 trades / -451.60 to 4 / -129.72, and reporting that as
    # "+321.88 USD since last time" would announce a fee refund the lane never earned.
    comparable = _prev(previous, "epoch") == epoch
    prev_trades = _prev(previous, "n_closed") if comparable else None
    prev_net = _prev(previous, "net") if comparable else None
    delta_trades = len(pnls) - prev_trades if prev_trades is not None else None
    delta_net = net - prev_net if prev_net is not None else None

    notes: list[str] = []
    if epoch is not None:
        notes.append(
            f"Bewertungsfenster ab {epoch} (Regime-Wechsel auf Tagesbars) — "
            "ältere Trades zählen nicht ins Urteil."
        )
    if previous is not None and not comparable:
        notes.append(
            "Vergleich zur letzten Auswertung ausgesetzt: sie wurde in einem anderen "
            "Bewertungsfenster gemessen. Ab der nächsten Auswertung zählt die Bewegung wieder."
        )
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
    settled = [r for r in (rejections or []) if r.get("sim_return") is not None]
    if settled:
        positive = sum(1 for r in settled if r["sim_return"] > 0)
        mean = sum(r["sim_return"] for r in settled) / len(settled)
        comparison = (
            f"die gehandelten Trades brachten netto {net:+.2f} USD über {len(pnls)} Abschlüsse"
            if pnls
            else "zum Vergleich steht kein abgeschlossener eigener Trade"
        )
        notes.append(
            f"Nicht-Trade-Buch: {len(settled)} verworfene Gelegenheiten aufgelöst, "
            f"{positive}/{len(settled)} wären im Plus gelandet, im Schnitt {mean:+.1%} "
            f"(brutto, simuliert — ohne Kosten); {comparison}."
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
        epoch=epoch,
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
