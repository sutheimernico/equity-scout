"""Piotroski F-Score: XBRL parsing, the nine criteria, persistence, collector, pitch line."""
from __future__ import annotations

import json

from equity_scout.fscore import (
    annual_series,
    collect_f_scores,
    compute_f_score,
    load_f_score,
    save_f_score,
)
from equity_scout.pitch import build_pitch, build_pitch_caption

TODAY = "2026-07-16"


def _entries(values: dict[int, float], form: str = "10-K") -> list[dict]:
    return [
        {"form": form, "fp": "FY", "fy": fy, "end": f"{fy}-12-31", "val": val}
        for fy, val in values.items()
    ]


def _payload(gaap: dict[str, dict[int, float]], shares: dict[int, float] | None = None) -> dict:
    facts: dict = {
        "us-gaap": {
            tag: {"units": {"USD": _entries(values)}} for tag, values in gaap.items()
        }
    }
    if shares is not None:
        facts["dei"] = {
            "EntityCommonStockSharesOutstanding": {"units": {"shares": _entries(shares)}}
        }
    return {"facts": facts}


def _strong_company() -> dict:
    return _payload(
        {
            "NetIncomeLoss": {2025: 100.0, 2024: 50.0},
            "NetCashProvidedByUsedInOperatingActivities": {2025: 120.0, 2024: 60.0},
            "Assets": {2025: 1000.0, 2024: 1000.0},
            "LongTermDebtNoncurrent": {2025: 100.0, 2024: 200.0},
            "AssetsCurrent": {2025: 300.0, 2024: 200.0},
            "LiabilitiesCurrent": {2025: 100.0, 2024: 100.0},
            "Revenues": {2025: 500.0, 2024: 400.0},
            "CostOfRevenue": {2025: 250.0, 2024: 240.0},  # margin 0.5 vs 0.4
        },
        shares={2025: 1000.0, 2024: 1000.0},
    )


def test_annual_series_takes_latest_end_per_fiscal_year():
    node = {"facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"form": "10-K", "fp": "FY", "fy": 2025, "end": "2024-12-31", "val": 900.0},
        {"form": "10-K", "fp": "FY", "fy": 2025, "end": "2025-12-31", "val": 1000.0},
        {"form": "10-K", "fp": "FY", "fy": 2024, "end": "2024-12-31", "val": 950.0},
        {"form": "10-Q", "fp": "Q2", "fy": 2025, "end": "2025-06-30", "val": 1234.0},
    ]}}}}}
    assert annual_series(node, ["Assets"]) == {2025: 1000.0, 2024: 950.0}


def test_annual_series_falls_back_through_tag_candidates():
    payload = _payload({"SalesRevenueNet": {2025: 500.0, 2024: 400.0}})
    series = annual_series(
        payload, ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                  "SalesRevenueNet"]
    )
    assert series == {2025: 500.0, 2024: 400.0}


def test_strong_company_scores_nine_of_nine():
    result = compute_f_score(_strong_company())
    assert result is not None
    assert result["score"] == 9
    assert result["evaluable"] == 9
    assert result["fiscal_year"] == 2025


def test_missing_inputs_become_unevaluable_not_failed():
    payload = _payload({
        "NetIncomeLoss": {2025: 100.0, 2024: 50.0},
        "NetCashProvidedByUsedInOperatingActivities": {2025: 120.0, 2024: 60.0},
        "Assets": {2025: 1000.0, 2024: 1000.0},
        "Revenues": {2025: 500.0, 2024: 400.0},
    })
    result = compute_f_score(payload)
    assert result is not None
    # leverage, liquidity, dilution, gross margin have no data -> None, not False
    assert result["criteria"]["leverage_down"] is None
    assert result["criteria"]["no_dilution"] is None
    assert result["evaluable"] == 5
    assert result["score"] == 5  # roa+, cfo+, roa up, cfo>ni, asset turnover up


def test_too_few_evaluable_criteria_yields_none():
    payload = _payload({
        "NetIncomeLoss": {2025: 100.0, 2024: 50.0},
        "Assets": {2025: 1000.0, 2024: 1000.0},
    })
    assert compute_f_score(payload) is None  # only 3 evaluable (roa, Δroa, turnover-less)


def test_single_fiscal_year_yields_none():
    payload = _payload({"NetIncomeLoss": {2025: 100.0}, "Assets": {2025: 1000.0}})
    assert compute_f_score(payload) is None


def test_save_and_load_roundtrip(tmp_path):
    db = str(tmp_path / "main.db")
    result = compute_f_score(_strong_company())
    assert result is not None
    save_f_score(db, "AAPL", result, TODAY)
    loaded = load_f_score(db, "AAPL")
    assert loaded is not None
    assert (loaded["score"], loaded["evaluable"], loaded["computed_on"]) == (9, 9, TODAY)
    assert loaded["criteria"]["roa_positive"] is True
    assert load_f_score(db, "MSFT") is None


def test_collector_skips_fresh_and_counts_failures(tmp_path):
    db = str(tmp_path / "main.db")
    fresh = compute_f_score(_strong_company())
    assert fresh is not None
    save_f_score(db, "FRESH", fresh, TODAY)  # already current -> skip
    calls: list[str] = []

    def fake_http_get(url: str) -> str:
        calls.append(url)
        if "0000000001" in url:
            return json.dumps(_strong_company())
        raise OSError("EDGAR 404")

    summary = collect_f_scores(
        db, ["FRESH", "GOOD", "BROKEN", "FOREIGN"],
        today=TODAY, http_get=fake_http_get,
        cik_map={"GOOD": "0000000001", "BROKEN": "0000000002"},
    )
    assert summary == {"computed": 1, "fresh": 1, "no_cik": 1, "failed": 1, "insufficient": 0}
    assert len(calls) == 2  # FRESH untouched, FOREIGN unfetchable
    loaded = load_f_score(db, "GOOD")
    assert loaded is not None and loaded["score"] == 9


def _pitch_entry() -> dict:
    return {
        "ticker": "EXE", "name": "Example Corp", "composite": 0.6,
        "breakdown": {"value": 0.5, "quality": 0.5, "momentum": 0.5, "growth": 0.5},
        "price": 90.0, "entry_zone_low": 85.0, "entry_zone_high": 95.0,
        "bucket": "balanced", "zone_note": "Kurs in der Entry-Zone (85.00–95.00).",
        "readings": [], "in_zone": True,
    }


def test_pitch_surfaces_carry_the_fscore_line():
    f_score = {"score": 7, "evaluable": 9, "fiscal_year": 2025, "criteria": {}}
    pitch = build_pitch(_pitch_entry(), ask=lambda q, c: "ok", f_score=f_score)
    assert "Bilanz-Trend (Piotroski F-Score): 7/9 — stark" in pitch
    assert "Ohne Einfluss auf den Score oben" in pitch
    caption = build_pitch_caption(_pitch_entry(), f_score=f_score)
    assert "📒 Bilanz-Trend 7/9 (stark)" in caption


def test_pitch_omits_fscore_when_absent():
    pitch = build_pitch(_pitch_entry(), ask=lambda q, c: "ok", f_score=None)
    assert "Piotroski" not in pitch
    assert "📒" not in build_pitch_caption(_pitch_entry())


def test_collector_counts_thin_data_separately_from_failures(tmp_path):
    """v9: a bank/REIT whose facts cannot fill 5 criteria is not a fetch failure —
    conflating the two made the summary line lie about EDGAR health."""
    db = str(tmp_path / "main.db")

    def fake_http_get(url: str) -> str:
        return json.dumps({"facts": {"us-gaap": {}}})

    summary = collect_f_scores(
        db, ["THIN"], today=TODAY, http_get=fake_http_get,
        cik_map={"THIN": "0000000003"},
    )
    assert summary["insufficient"] == 1
    assert summary["failed"] == 0
    assert summary["computed"] == 0
