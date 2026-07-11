"""Person track-record core: parsing, gating, horizons, recency weighting."""
from __future__ import annotations

import pandas as pd

from equity_scout.evidence.person_track import (
    Call,
    calls_from_events,
    calls_from_filer_payload,
    score_persons,
)

NOW = "2026-07-10T12:00:00+00:00"


def _payload(trades: list[dict], name: str = "Jane Doe") -> dict:
    return {"filer": {"full_name": name}, "trades": trades}


def _trade(**overrides) -> dict:
    base = {
        "transaction_type": "Purchase",
        "asset_type": "ST",
        "ticker": "AAA",
        "filing_date": "2026-01-05",
        "transaction_date": "2026-01-02",
    }
    base.update(overrides)
    return base


def test_calls_from_filer_payload_keeps_stock_purchases_and_counts_skips():
    payload = _payload(
        [
            _trade(),
            _trade(transaction_type="Sale (Full)"),  # sales are not comparable signals
            _trade(asset_type="Stock Option"),
            _trade(ticker=None),
            _trade(filing_date=None, notification_date=None),
            _trade(ticker="aaa"),  # same ticker+day as the first -> collapsed
        ]
    )
    calls, counters = calls_from_filer_payload(payload)
    assert [c.ticker for c in calls] == ["AAA"]
    assert calls[0].person == "Jane Doe"
    assert calls[0].t0 == "2026-01-05"  # filing date, not transaction date
    assert counters == {"rows": 6, "kept": 1, "not_purchase": 1, "not_stock": 1,
                        "no_ticker": 1, "no_date": 1}


def test_calls_from_events_names_politician_or_fund_and_skips_themes():
    events = [
        {"source": "congress", "ticker": "AAA", "event_date": "2026-01-07",
         "details": {"politician": "Jane Doe", "filing_date": "2026-01-05"}},
        {"source": "thirteen_f", "ticker": "BBB", "event_date": "2026-01-08",
         "details": {"fund": "Scion Asset Management", "filed_at": "2026-01-08"}},
        {"source": "news_theme", "ticker": "CCC", "event_date": "2026-01-09",
         "details": {"theme": "ai chips"}},
    ]
    calls = calls_from_events(events)
    assert [(c.person, c.t0) for c in calls] == [
        ("Jane Doe", "2026-01-05"),
        ("Scion Asset Management", "2026-01-08"),
    ]


def _panel(winner_rate: float = 1.0008, loser_rate: float = 0.9996) -> pd.DataFrame:
    idx = pd.bdate_range("2025-06-01", periods=400)
    n = len(idx)
    return pd.DataFrame(
        {
            "SPY": [100.0 * 1.0002**i for i in range(n)],
            "WIN": [100.0 * winner_rate**i for i in range(n)],
            "LOSE": [100.0 * loser_rate**i for i in range(n)],
        },
        index=idx,
    )


def _calls(person: str, ticker: str, n: int, first_day: str = "2025-07-01") -> list[Call]:
    days = pd.bdate_range(first_day, periods=n)
    return [
        Call(person=person, source="congress", ticker=ticker, t0=d.date().isoformat())
        for d in days
    ]


def test_score_persons_measures_winner_and_loser_against_spy():
    calls = _calls("Winner", "WIN", 6) + _calls("Loser", "LOSE", 6)
    scores = score_persons(calls, _panel(), now=NOW)
    winner, loser = scores["Winner"], scores["Loser"]
    assert winner.scoreable and winner.n_calls == 6
    assert winner.hit_rate_long == 1.0
    assert winner.weighted_score is not None and winner.weighted_score > 0
    assert loser.hit_rate_long == 0.0
    assert loser.weighted_score is not None and loser.weighted_score < 0


def test_score_persons_gates_small_samples_honestly():
    scores = score_persons(_calls("Newbie", "WIN", 3), _panel(), now=NOW)
    newbie = scores["Newbie"]
    assert not newbie.scoreable
    assert newbie.weighted_score is None  # never a number below the gate
    assert newbie.n_calls == 3  # the sample size itself is stated
    assert newbie.hit_rate_long == 1.0  # raw facts stay visible


def test_score_persons_counts_unresolvable_calls_instead_of_guessing():
    calls = _calls("Jane", "WIN", 5) + [
        Call(person="Jane", source="congress", ticker="MISSING", t0="2025-07-01"),
        # t0 beyond the panel's end: forward window not observable.
        Call(person="Jane", source="congress", ticker="WIN", t0="2027-05-01"),
    ]
    scores = score_persons(calls, _panel(), now=NOW)
    assert scores["Jane"].n_calls == 5
    assert scores["Jane"].n_unresolvable == 2


def test_score_persons_weights_recent_calls_higher():
    """Same mixed results, opposite order: the person whose WINS are recent scores higher."""
    early_win = _calls("EarlyWin", "WIN", 5, first_day="2025-07-01") + _calls(
        "EarlyWin", "LOSE", 5, first_day="2026-01-05"
    )
    late_win = _calls("LateWin", "LOSE", 5, first_day="2025-07-01") + _calls(
        "LateWin", "WIN", 5, first_day="2026-01-05"
    )
    scores = score_persons(early_win + late_win, _panel(), now=NOW)
    assert scores["LateWin"].weighted_score > scores["EarlyWin"].weighted_score
    # Unweighted long-horizon means barely differ — the ordering is the decay's work.
    assert abs(
        scores["LateWin"].mean_abnormal_long - scores["EarlyWin"].mean_abnormal_long
    ) < 0.02


def test_score_persons_requires_benchmark_column():
    import pytest

    with pytest.raises(ValueError, match="SPY"):
        score_persons([], pd.DataFrame({"AAA": [1.0]}), now=NOW)


def test_score_persons_disambiguates_person_present_in_two_sources():
    calls = _calls("Dual", "WIN", 5)
    calls += [
        Call(person="Dual", source="thirteen_f", ticker="WIN", t0="2025-07-01"),
    ] * 1
    scores = score_persons(calls, _panel(), now=NOW)
    assert set(scores) == {"Dual·congress", "Dual·thirteen_f"}
    assert scores["Dual·congress"].n_calls == 5


def test_score_persons_maps_share_class_dots_to_yahoo_dashes():
    """Disclosures say BRK.B, Yahoo says BRK-B — the call must still resolve."""
    panel = _panel().rename(columns={"WIN": "BRK-B"})
    calls = [
        Call(person="Jane", source="congress", ticker="BRK.B",
             t0=d.date().isoformat())
        for d in pd.bdate_range("2025-07-01", periods=5)
    ]
    scores = score_persons(calls, panel, now=NOW)
    assert scores["Jane"].n_calls == 5
    assert scores["Jane"].n_unresolvable == 0


def test_score_persons_counts_benchmark_buys_as_unmeasurable():
    """A SPY purchase is not a stock call — no self-vs-self edge, no crash."""
    calls = _calls("Jane", "WIN", 5) + _calls("Jane", "SPY", 2)
    scores = score_persons(calls, _panel(), now=NOW)
    assert scores["Jane"].n_calls == 5
    assert scores["Jane"].n_unresolvable == 2


def test_scoreable_requires_the_full_long_horizon_not_just_short():
    """Calls 21-62 trading days old resolve @1M but not @3M: that person is 'noch
    nicht 3M-reif' — scoreable must stay False and the score None, never a
    fabricated 0 % (review finding 2026-07-11)."""
    panel = _panel()
    # t0s ~30 business days before the panel ends: short window observable, long not.
    calls = [
        Call(person="Fresh", source="congress", ticker="WIN",
             t0=panel.index[-30 + i].date().isoformat())
        for i in range(5)
    ]
    scores = score_persons(calls, panel, now=NOW)
    fresh = scores["Fresh"]
    assert fresh.n_calls == 5  # the short horizon DID measure
    assert fresh.hit_rate_short is not None
    assert not fresh.scoreable  # ... but the headline 3M gate is not met
    assert fresh.weighted_score is None
    assert fresh.hit_rate_long is None
