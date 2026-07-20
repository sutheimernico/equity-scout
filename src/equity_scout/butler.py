"""Monthly ETF core savings-plan block (v9 Anlage-Butler).

Pure math + rendering: the registry's Multi-Strategie-Mix target weights on the
shared ETF panel become whole-EUR amounts for a configurable monthly budget.
Core/satellite split is fixed at 80/20 — one decision, not a config surface.
EUR amounts are budget splits (weight x budget), deliberately no FX: the reader
allocates euros at their broker, the model ranks asset classes.
"""
from __future__ import annotations

import sys

import pandas as pd

from equity_scout.etf_universe import ETF_BY_TICKER
from equity_scout.market import MarketView
from equity_scout.strategies.base import normalise_weights
from equity_scout.strategies.registry import default_strategies
from equity_scout.telegram_client import escape_html

DEFAULT_MONTHLY_BUDGET_EUR = 500
CORE_SHARE = 0.8
_MIX_NAME = "Multi-Strategie-Mix"
MONTH_NAMES = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
               "August", "September", "Oktober", "November", "Dezember"]


def monthly_budget(env: dict) -> int:
    raw = env.get("COPILOT_MONTHLY_BUDGET")
    if not raw:
        return DEFAULT_MONTHLY_BUDGET_EUR
    try:
        return max(1, int(raw))
    except ValueError:
        print(
            f"COPILOT_MONTHLY_BUDGET ist keine Zahl — nutze Default {DEFAULT_MONTHLY_BUDGET_EUR}.",
            file=sys.stderr,
        )
        return DEFAULT_MONTHLY_BUDGET_EUR


def build_core_plan(panel, monthly_budget_eur: int) -> dict | None:
    """Whole-EUR core allocation from the Mix strategy's current target weights.
    None when the panel is missing or the strategy cannot decide (short/stale
    panel) — honest absence beats a made-up allocation."""
    if panel is None:
        return None
    strategy = next(
        (s for s in default_strategies() if getattr(s, "name", "") == _MIX_NAME), None
    )
    if strategy is None:
        return None
    as_of = panel.dates[-1] + pd.Timedelta(days=1)
    try:
        weights = normalise_weights(strategy.decide(as_of, MarketView(panel, as_of)))
    except Exception:  # noqa: BLE001 - a broken panel must not break the digest
        return None
    if not weights:
        return None
    core_budget = round(monthly_budget_eur * CORE_SHARE)
    positions = []
    for tw in sorted(weights, key=lambda t: -t.weight):
        amount = int(round(tw.weight * core_budget))
        if amount < 1:
            continue
        inst = ETF_BY_TICKER.get(tw.ticker)
        positions.append({
            "ticker": tw.ticker,
            "name": inst.name if inst is not None else tw.ticker,
            "amount_eur": amount,
        })
    if not positions:
        return None
    # Per-position round() can overshoot the core budget by a few EUR in aggregate
    # (three 33.5s round to 34+34+33). The largest position absorbs the overhang so
    # the block never asks the reader to invest more than the stated core budget.
    overshoot = sum(p["amount_eur"] for p in positions) - core_budget
    if overshoot > 0:
        positions[0]["amount_eur"] -= overshoot
    cash_rest = core_budget - sum(p["amount_eur"] for p in positions)
    return {
        "budget": monthly_budget_eur,
        "core_budget": core_budget,
        "satellite_budget": monthly_budget_eur - core_budget,
        "positions": positions,
        "cash_rest": cash_rest,
    }


def render_core_block(plan: dict, *, month_label: str, html: bool) -> str:
    """One <b> pair max per line (digest split discipline); all dynamics escaped."""

    def _head(text: str) -> str:
        return f"<b>{escape_html(text)}</b>" if html else text

    def _line(text: str) -> str:
        return escape_html(text) if html else text

    lines = [_head(
        f"💶 Dein Monats-Sparplan {month_label} — Beispielrechnung mit {plan['budget']} €/Monat:"
    )]
    lines.append(_line(
        f"Kern ({round(CORE_SHARE * 100)} % = {plan['core_budget']} €) — {_MIX_NAME}, regelbasiert:"
    ))
    for p in plan["positions"]:
        lines.append(_line(f"  • {p['amount_eur']} € — {p['name']} ({p['ticker']})"))
    if plan["cash_rest"] > 0:
        lines.append(_line(f"  • {plan['cash_rest']} € bleiben als Cash-Rest"))
    lines.append(_line(
        f"Satellit ({round((1 - CORE_SHARE) * 100)} % = {plan['satellite_budget']} €):"
        " für einzelne Aktien-Ideen unten — oder ebenfalls in den Kern."
    ))
    lines.append(_line(
        "US-Ticker aus dem Modell — beim eigenen Broker das UCITS-Pendant wählen."
        " Betrag anpassbar über COPILOT_MONTHLY_BUDGET. Keine Anlageberatung."
    ))
    return "\n".join(lines)


def core_running_line(*, html: bool) -> str:
    text = "💶 Sparplan-Kern: läuft — der volle Monatsplan kommt einmal pro Monat."
    return escape_html(text) if html else text
