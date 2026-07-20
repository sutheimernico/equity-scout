"""Piotroski F-Score from SEC EDGAR XBRL company facts (v8 D2).

Nine binary balance-sheet checks (Piotroski 2000) computed from OFFICIAL audited
numbers — the `companyfacts` API needs only the polite EDGAR user agent, no key.
This deliberately does NOT use yfinance fundamentals (known patchy, see
docs/factors.md "honest limitations") and deliberately does NOT feed the
universe-wide quality percentile: company facts are fetched per WATCHLIST ticker
only (a full-universe sweep would be gigabytes per run), and ranking a metric that
exists for 30 names against 6 000 that lack it would be dishonest. The score is a
standalone, clearly-labelled balance-trend annotation on the pitch surfaces.

Honesty rules: a criterion whose inputs are missing is None (not failed); a score
is only reported when at least MIN_EVALUABLE of the nine criteria are evaluable;
non-US names without EDGAR filings simply have no score. Scores refresh at most
every FRESH_DAYS days — fundamentals move with quarterly/annual reports, not daily.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.data.cache import is_fresh

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
FRESH_DAYS = 30
MIN_EVALUABLE = 5

# XBRL tag candidates per input, first series with two fiscal years wins.
_REVENUE_TAGS = [
    "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
]
_SHARES_SOURCES = [  # (taxonomy, tag, unit)
    ("us-gaap", "CommonStockSharesOutstanding", "shares"),
    ("dei", "EntityCommonStockSharesOutstanding", "shares"),
    ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", "shares"),
]

CRITERIA_LABELS = {
    "roa_positive": "Gewinn positiv (ROA > 0)",
    "cfo_positive": "Operativer Cashflow positiv",
    "roa_improving": "ROA verbessert",
    "cfo_exceeds_net_income": "Cashflow > Gewinn (Qualität der Gewinne)",
    "leverage_down": "Verschuldungsgrad gesunken",
    "liquidity_up": "Liquidität (Current Ratio) verbessert",
    "no_dilution": "Keine Verwässerung (Aktienzahl nicht gestiegen)",
    "gross_margin_up": "Bruttomarge verbessert",
    "asset_turnover_up": "Kapitalumschlag verbessert",
}


def annual_series(
    payload: dict, tags: list[str], unit: str = "USD", taxonomy: str = "us-gaap"
) -> dict[int, float]:
    """fiscal year -> value from 10-K FY entries. A 10-K restates prior-year figures
    under the same `fy`, so per year the entry with the LATEST `end` wins (that is the
    filing's own period, and amendments supersede originals). First tag candidate with
    at least two fiscal years wins; otherwise {}."""
    for tag in tags:
        entries = (
            payload.get("facts", {}).get(taxonomy, {}).get(tag, {}).get("units", {}).get(unit)
            or []
        )
        best: dict[int, tuple[str, float]] = {}
        for entry in entries:
            if not str(entry.get("form", "")).startswith("10-K"):
                continue
            if entry.get("fp") != "FY" or not entry.get("fy") or entry.get("val") is None:
                continue
            year, end = int(entry["fy"]), str(entry.get("end", ""))
            if year not in best or end > best[year][0]:
                best[year] = (end, float(entry["val"]))
        if len(best) >= 2:
            return {year: value for year, (_, value) in best.items()}
    return {}


def _shares_series(payload: dict) -> dict[int, float]:
    for taxonomy, tag, unit in _SHARES_SOURCES:
        series = annual_series(payload, [tag], unit=unit, taxonomy=taxonomy)
        if series:
            return series
    return {}


def compute_f_score(payload: dict) -> dict | None:
    """The nine Piotroski criteria over the two most recent 10-K fiscal years.
    Returns {"score", "evaluable", "fiscal_year", "prev_fiscal_year", "criteria"}
    or None when fewer than MIN_EVALUABLE criteria have data."""
    net_income = annual_series(payload, ["NetIncomeLoss"])
    cfo = annual_series(payload, ["NetCashProvidedByUsedInOperatingActivities"])
    assets = annual_series(payload, ["Assets"])
    long_term_debt = annual_series(payload, ["LongTermDebtNoncurrent", "LongTermDebt"])
    current_assets = annual_series(payload, ["AssetsCurrent"])
    current_liabilities = annual_series(payload, ["LiabilitiesCurrent"])
    revenue = annual_series(payload, _REVENUE_TAGS)
    gross_profit = annual_series(payload, ["GrossProfit"])
    cost_of_revenue = annual_series(payload, ["CostOfRevenue", "CostOfGoodsAndServicesSold"])
    shares = _shares_series(payload)

    anchor_years = sorted(set(net_income) & set(assets), reverse=True)
    if len(anchor_years) < 2:
        return None
    cur, prev = anchor_years[0], anchor_years[1]

    def ratio(numerator: dict[int, float], denominator: dict[int, float], year: int) -> float | None:
        a, b = numerator.get(year), denominator.get(year)
        if a is None or b is None or b == 0:
            return None
        return a / b

    def delta_up(numerator: dict[int, float], denominator: dict[int, float]) -> bool | None:
        now, before = ratio(numerator, denominator, cur), ratio(numerator, denominator, prev)
        if now is None or before is None:
            return None
        return now > before

    def gross_margin(year: int) -> float | None:
        profit = gross_profit.get(year)
        if profit is None and year in revenue and year in cost_of_revenue:
            profit = revenue[year] - cost_of_revenue[year]
        if profit is None or revenue.get(year) in (None, 0):
            return None
        return profit / revenue[year]

    roa_cur, roa_prev = ratio(net_income, assets, cur), ratio(net_income, assets, prev)
    margin_cur, margin_prev = gross_margin(cur), gross_margin(prev)
    leverage = delta_up(long_term_debt, assets)
    criteria: dict[str, bool | None] = {
        "roa_positive": None if roa_cur is None else roa_cur > 0,
        "cfo_positive": None if cur not in cfo else cfo[cur] > 0,
        "roa_improving": None if roa_cur is None or roa_prev is None else roa_cur > roa_prev,
        "cfo_exceeds_net_income": (
            None if cur not in cfo or cur not in net_income else cfo[cur] > net_income[cur]
        ),
        "leverage_down": None if leverage is None else not leverage,
        "liquidity_up": delta_up(current_assets, current_liabilities),
        "no_dilution": (
            None if cur not in shares or prev not in shares else shares[cur] <= shares[prev]
        ),
        "gross_margin_up": (
            None if margin_cur is None or margin_prev is None else margin_cur > margin_prev
        ),
        "asset_turnover_up": delta_up(revenue, assets),
    }
    evaluable = sum(1 for value in criteria.values() if value is not None)
    if evaluable < MIN_EVALUABLE:
        return None
    return {
        "score": sum(1 for value in criteria.values() if value is True),
        "evaluable": evaluable,
        "fiscal_year": cur,
        "prev_fiscal_year": prev,
        "criteria": criteria,
    }


# --- persistence (main db; refreshed at most every FRESH_DAYS days) --------------


def init_fscore_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS f_scores (
                ticker TEXT PRIMARY KEY,
                computed_on TEXT NOT NULL,
                score INTEGER NOT NULL,
                evaluable INTEGER NOT NULL,
                fiscal_year INTEGER NOT NULL,
                criteria TEXT NOT NULL
            )"""
        )


def save_f_score(db_path: str, ticker: str, result: dict, computed_on: str) -> None:
    init_fscore_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO f_scores (ticker, computed_on, score, evaluable, fiscal_year,"
            " criteria) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(ticker) DO UPDATE SET computed_on=excluded.computed_on,"
            " score=excluded.score, evaluable=excluded.evaluable,"
            " fiscal_year=excluded.fiscal_year, criteria=excluded.criteria",
            (ticker, computed_on, result["score"], result["evaluable"],
             result["fiscal_year"], json.dumps(result["criteria"])),
        )


def load_f_score(db_path: str, ticker: str) -> dict | None:
    init_fscore_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT computed_on, score, evaluable, fiscal_year, criteria FROM f_scores"
            " WHERE ticker = ?",
            (ticker,),
        ).fetchone()
    if row is None:
        return None
    return {
        "computed_on": row[0], "score": row[1], "evaluable": row[2],
        "fiscal_year": row[3], "criteria": json.loads(row[4]),
    }


def collect_f_scores(
    db_path: str,
    tickers: list[str],
    *,
    today: str,
    http_get: Callable[[str], str],
    cik_map: dict[str, str],
) -> dict:
    """Refresh stale/missing scores for `tickers`. Per ticker: fresh cache -> skip;
    no CIK (non-US listing) -> skip, honest absence; fetch/parse failure -> skip and
    count (one bad name never kills the batch); facts too thin for MIN_EVALUABLE
    criteria (banks/REITs use different taxonomy tags) -> counted as `insufficient`,
    not as a failure — the summary must not read data shape as EDGAR breakage.
    Returns a summary dict."""
    computed = skipped_fresh = no_cik = failed = insufficient = 0
    for ticker in tickers:
        cached = load_f_score(db_path, ticker)
        if cached is not None and is_fresh(cached["computed_on"], today, FRESH_DAYS):
            skipped_fresh += 1
            continue
        cik = cik_map.get(ticker.upper())
        if cik is None:
            no_cik += 1
            continue
        try:
            payload = json.loads(http_get(COMPANYFACTS_URL.format(cik=cik)))
            result = compute_f_score(payload)
        except Exception:  # noqa: BLE001 - per-ticker resilience, counted not hidden
            failed += 1
            continue
        if result is None:
            insufficient += 1
            continue
        save_f_score(db_path, ticker, result, today)
        computed += 1
    return {"computed": computed, "fresh": skipped_fresh, "no_cik": no_cik,
            "failed": failed, "insufficient": insufficient}
