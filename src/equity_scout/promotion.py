"""Evidence-gated promotion of arena lanes into Auto-Depot sleeves (v12 I2).

The honest version of "short term soll auch Geld machen": an arena lane only earns depot
capital after PROVING itself on realised paper trades — net of costs, over a minimum
sample and time span. Until then the arena stays a measurement instrument. Pure logic:
storage-shaped rows in, verdict plus a named list of missing criteria out — the surfaces
render the checklist, they never re-derive it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class PromotionConfig:
    min_trades: int = 30  # realised (closed) trades — open buys prove nothing
    min_days_active: int = 60  # calendar days since the lane's first valuation
    min_profit_factor: float = 1.1  # gross wins / gross losses, after costs


def lane_promotion_status(
    trades: list[dict],
    valuations: list[dict],
    cfg: PromotionConfig = PromotionConfig(),
    *,
    today: str,
) -> dict:
    """Verdict for one lane. `trades` rows carry `realized_pnl` (None on buys, after-cost
    on sells — shortterm_book convention); `valuations` must be chronologically loaded
    (shortterm_storage returns ASC). Every failing criterion lands in `missing`."""
    realized = [
        float(t["realized_pnl"]) for t in trades if t.get("realized_pnl") is not None
    ]
    n_trades = len(realized)
    net_pnl = sum(realized)
    wins = sum(p for p in realized if p > 0)
    losses = -sum(p for p in realized if p < 0)
    profit_factor: float | None
    if losses > 0:
        profit_factor = wins / losses
    elif wins > 0:
        profit_factor = float("inf")  # no realised loss yet — the sample gate still holds
    else:
        profit_factor = None

    days_active = 0
    if valuations:
        first = date.fromisoformat(valuations[0]["created_at"][:10])
        days_active = (date.fromisoformat(today) - first).days

    missing: list[str] = []
    if n_trades < cfg.min_trades:
        missing.append(f"erst {n_trades}/{cfg.min_trades} realisierte Trades")
    if days_active < cfg.min_days_active:
        missing.append(f"erst {days_active}/{cfg.min_days_active} Tage aktiv")
    if net_pnl <= 0:
        missing.append(f"Netto-P&L nach Kosten nicht positiv ({net_pnl:+,.2f} $)")
    if profit_factor is None or profit_factor < cfg.min_profit_factor:
        shown = "—" if profit_factor is None else f"{profit_factor:.2f}"
        missing.append(f"Profit-Faktor {shown} < {cfg.min_profit_factor}")

    return {
        "realized_trades": n_trades,
        "days_active": days_active,
        "net_pnl": net_pnl,
        "profit_factor": None if profit_factor is None else float(profit_factor),
        "eligible": not missing,
        "missing": missing,
    }


def trailing_net_pnl(trades: list[dict], *, today: str, days: int = 60) -> float:
    """Realised net P&L over the trailing window — the DEMOTION criterion (v12 I3).
    Deliberately laxer than the entry gate (hysteresis): a borderline lane must not
    flap in and out of the depot every month."""
    cutoff = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    return sum(
        float(t["realized_pnl"]) for t in trades
        if t.get("realized_pnl") is not None and (t.get("executed_at") or "")[:10] >= cutoff
    )
