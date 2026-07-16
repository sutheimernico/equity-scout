"""Event-reaction study tests (Strang B4): hypothetical paper-reaction return over
1d/5d from daily closes, honest latency, predict-then-resolve gating, and the
aggregated edge-monitor view. No network, no wall clock — prices and seen_at are
always injected."""
from __future__ import annotations

import pandas as pd

from equity_scout.evidence.event_reactions import (
    ONE_HOUR_NOT_MEASURABLE_REASON,
    _anchor,
    aggregate_reactions,
    compute_reaction_returns,
    init_event_reactions_db,
    latency_minutes,
    pending_reactions,
    queue_pending_reactions,
    resolve_reaction,
    resolved_reactions,
)

# 6 consecutive business days: anchor (100) -> +1d (105, +5%) -> ... -> +5d (150, +50%).
DATES = pd.bdate_range("2026-01-05", periods=6)
FULL_CLOSES = pd.Series([100.0, 105.0, 108.0, 111.0, 120.0, 150.0], index=DATES)
# Latency tests need a fixed intraday seen_at; anchor tests need one AFTER the anchor
# day's close settled (16:00 EST = 21:00 UTC on 2026-01-05, a winter/EST date), so
# 2026-01-05's close is the honest anchor.
SEEN_AT = "2026-01-05T09:00:00+00:00"
SEEN_AT_POST_CLOSE = "2026-01-05T22:00:00+00:00"


def _event(**overrides) -> dict:
    base = dict(
        ticker="AAPL",
        event_type="beat",
        source="news",
        published_at="2026-01-05T08:45:00+00:00",
        seen_at=SEEN_AT,
        detail="Apple beats estimates",
        event_key="news-AAPL-abc123",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# latency_minutes
# ---------------------------------------------------------------------------


def test_latency_minutes_computed_from_seen_and_published():
    assert latency_minutes("2026-01-05T08:45:00+00:00", "2026-01-05T09:00:00+00:00") == 15.0


def test_latency_minutes_null_when_published_at_missing():
    assert latency_minutes(None, SEEN_AT) is None


def test_latency_minutes_handles_date_only_published_at():
    # News published_at is often date-only (event_classifier.py); midnight is the
    # honest anchor, not a fabricated time-of-day.
    assert latency_minutes("2026-01-05", "2026-01-05T09:00:00+00:00") == 540.0


# ---------------------------------------------------------------------------
# compute_reaction_returns — hand-verified sign + pending gate
# ---------------------------------------------------------------------------


def test_beat_reaction_return_is_positive_and_hand_verified():
    result = compute_reaction_returns(FULL_CLOSES, SEEN_AT_POST_CLOSE, "beat")
    assert result["status"] == "resolved"
    assert result["ret_1d"] == 0.05  # (105 - 100) / 100
    assert result["ret_5d"] == 0.5  # (150 - 100) / 100


def test_miss_reaction_return_is_sign_flipped():
    result = compute_reaction_returns(FULL_CLOSES, SEEN_AT_POST_CLOSE, "miss")
    assert result["status"] == "resolved"
    assert result["ret_1d"] == -0.05
    assert result["ret_5d"] == -0.5


def test_guidance_up_and_down_are_directional_too():
    up = compute_reaction_returns(FULL_CLOSES, SEEN_AT_POST_CLOSE, "guidance_up")
    down = compute_reaction_returns(FULL_CLOSES, SEEN_AT_POST_CLOSE, "guidance_down")
    assert up["ret_5d"] == 0.5
    assert down["ret_5d"] == -0.5


def test_unknown_and_earnings_filed_are_skipped_not_evaluated():
    for event_type in ("unknown", "earnings_filed", "other_8k"):
        result = compute_reaction_returns(FULL_CLOSES, SEEN_AT_POST_CLOSE, event_type)
        assert result["status"] == "skipped"
        assert result["ret_1d"] is None
        assert result["ret_5d"] is None


def test_fresh_event_without_enough_trading_days_stays_pending():
    # Only 4 rows of future data past the anchor — the 5d window is not observable yet.
    short_closes = FULL_CLOSES.iloc[:4]
    result = compute_reaction_returns(short_closes, SEEN_AT_POST_CLOSE, "beat")
    assert result["status"] == "pending"
    assert result["ret_1d"] is None  # never filled from an incomplete window
    assert result["ret_5d"] is None


def test_intraday_seen_at_anchors_on_prior_close_not_todays_jump():
    # THE look-ahead regression: an event-day price jump (07-14 close 102 -> 07-15
    # close 150) with an INTRADAY seen_at on 07-15 (US market still open). 07-15's
    # close is not known yet, so the anchor must be 07-14 (102) and the whole 102->150
    # event-day reaction lands INSIDE the 1d window — not fall before it. The buggy
    # .normalize() anchor picked 07-15 (150) and measured the jump away entirely.
    dates = pd.bdate_range("2026-07-13", periods=7)  # Mon 07-13 .. Tue 07-21
    closes = pd.Series([100.0, 102.0, 150.0, 151.0, 152.0, 153.0, 160.0], index=dates)
    # 14:00 UTC = 10:00 EDT on 2026-07-15 — well before the 16:00 EDT close.
    result = compute_reaction_returns(closes, "2026-07-15T14:00:00+00:00", "beat")
    assert result["status"] == "resolved"
    assert round(result["ret_1d"], 6) == round((150.0 - 102.0) / 102.0, 6)  # jump captured
    assert round(result["ret_5d"], 6) == round((160.0 - 102.0) / 102.0, 6)


def test_post_close_seen_at_anchors_on_todays_close():
    # After 16:00 ET the day's close is settled, so a post-close seen_at anchors on
    # TODAY (07-15), not the prior day — the mirror image of the intraday case.
    dates = pd.bdate_range("2026-07-13", periods=8)  # 07-15 at pos 2, +5 = pos 7
    closes = pd.Series(
        [100.0, 102.0, 150.0, 151.0, 152.0, 153.0, 160.0, 170.0], index=dates
    )
    # 20:30 UTC = 16:30 EDT on 2026-07-15 — after the close.
    result = compute_reaction_returns(closes, "2026-07-15T20:30:00+00:00", "beat")
    assert result["status"] == "resolved"
    assert round(result["ret_1d"], 6) == round((151.0 - 150.0) / 150.0, 6)
    assert round(result["ret_5d"], 6) == round((170.0 - 150.0) / 150.0, 6)


def test_market_close_boundary_summer_edt():
    # EDT (UTC-4): 16:00 ET = 20:00 UTC on 2026-07-15 (a Wednesday). Exactly at close
    # the day is settled (<=); one minute before it is not.
    closes = pd.Series(
        [1.0, 2.0, 3.0], index=pd.DatetimeIndex(["2026-07-14", "2026-07-15", "2026-07-16"])
    )
    assert _anchor(closes, "2026-07-15T20:00:00+00:00") == pd.Timestamp("2026-07-15")
    assert _anchor(closes, "2026-07-15T19:59:00+00:00") == pd.Timestamp("2026-07-14")


def test_market_close_boundary_winter_est():
    # EST (UTC-5): 16:00 ET = 21:00 UTC on 2026-01-15 (a Thursday) — one hour later in
    # UTC than the summer case, which is exactly what zoneinfo must get right.
    closes = pd.Series(
        [1.0, 2.0, 3.0], index=pd.DatetimeIndex(["2026-01-14", "2026-01-15", "2026-01-16"])
    )
    assert _anchor(closes, "2026-01-15T21:00:00+00:00") == pd.Timestamp("2026-01-15")
    assert _anchor(closes, "2026-01-15T20:59:00+00:00") == pd.Timestamp("2026-01-14")


def test_naive_seen_at_treated_as_utc_conservatively():
    # No offset -> UTC (repo convention), the conservative reading: 18:00 UTC = 14:00
    # EDT on 07-15, still intraday -> anchor the prior day, never a look-ahead.
    closes = pd.Series(
        [1.0, 2.0, 3.0], index=pd.DatetimeIndex(["2026-07-14", "2026-07-15", "2026-07-16"])
    )
    assert _anchor(closes, "2026-07-15T18:00:00") == pd.Timestamp("2026-07-14")


def test_no_price_data_before_seen_at_stays_pending():
    result = compute_reaction_returns(FULL_CLOSES, "2026-01-01T00:00:00+00:00", "beat")
    assert result["status"] == "pending"


# ---------------------------------------------------------------------------
# storage: queue (predict) / pending / resolve — mirrors ml/prediction_ledger.py
# ---------------------------------------------------------------------------


def test_init_creates_table_without_error(tmp_path):
    db = str(tmp_path / "ev.db")
    init_event_reactions_db(db)
    init_event_reactions_db(db)  # idempotent CREATE TABLE IF NOT EXISTS


def test_queue_pending_reactions_only_queues_directional_events(tmp_path):
    db = str(tmp_path / "ev.db")
    events = [
        _event(event_type="beat", event_key="k1"),
        _event(event_type="unknown", event_key="k2"),
        _event(event_type="earnings_filed", event_key="k3"),
    ]
    inserted = queue_pending_reactions(db, events)
    assert [e["event_key"] for e in inserted] == ["k1"]
    pending = pending_reactions(db)
    assert [p["event_key"] for p in pending] == ["k1"]
    assert pending[0]["status"] == "pending"


def test_queue_pending_reactions_is_idempotent_by_event_key(tmp_path):
    db = str(tmp_path / "ev.db")
    events = [_event(event_key="k1")]
    first = queue_pending_reactions(db, events)
    second = queue_pending_reactions(db, events)
    assert len(first) == 1
    assert second == []
    assert len(pending_reactions(db)) == 1


def test_queue_pending_reactions_stores_latency(tmp_path):
    db = str(tmp_path / "ev.db")
    queue_pending_reactions(db, [_event(event_key="k1")])
    assert pending_reactions(db)[0]["latency_minutes"] == 15.0


def test_queue_pending_reactions_missing_published_at_stores_null_latency(tmp_path):
    db = str(tmp_path / "ev.db")
    queue_pending_reactions(db, [_event(event_key="k1", published_at=None)])
    assert pending_reactions(db)[0]["latency_minutes"] is None


def test_resolve_reaction_fills_returns_and_flips_status(tmp_path):
    db = str(tmp_path / "ev.db")
    queue_pending_reactions(db, [_event(event_key="k1", event_type="beat")])
    ok = resolve_reaction(db, "k1", ret_1d=0.05, ret_5d=0.5)
    assert ok is True
    assert pending_reactions(db) == []
    resolved = resolved_reactions(db)
    assert resolved[0]["ret_1d"] == 0.05
    assert resolved[0]["ret_5d"] == 0.5
    assert resolved[0]["status"] == "resolved"


def test_double_resolve_is_refused_and_keeps_first_resolution(tmp_path):
    db = str(tmp_path / "ev.db")
    queue_pending_reactions(db, [_event(event_key="k1", event_type="beat")])
    resolve_reaction(db, "k1", ret_1d=0.05, ret_5d=0.5)
    second = resolve_reaction(db, "k1", ret_1d=-1.0, ret_5d=-1.0)
    assert second is False
    assert resolved_reactions(db)[0]["ret_5d"] == 0.5  # first resolution stands


def test_resolved_reactions_filters_by_ticker(tmp_path):
    db = str(tmp_path / "ev.db")
    queue_pending_reactions(
        db, [_event(event_key="k1", ticker="AAPL"), _event(event_key="k2", ticker="MSFT")]
    )
    resolve_reaction(db, "k1", ret_1d=0.01, ret_5d=0.02)
    resolve_reaction(db, "k2", ret_1d=0.03, ret_5d=0.04)
    assert {r["event_key"] for r in resolved_reactions(db, ticker="MSFT")} == {"k2"}
    assert {r["event_key"] for r in resolved_reactions(db, ticker="aapl")} == {"k1"}  # case-insensitive


# ---------------------------------------------------------------------------
# aggregate_reactions — the honest "is there anything to harvest" answer
# ---------------------------------------------------------------------------


def test_aggregate_reactions_empty_db_is_honest(tmp_path):
    db = str(tmp_path / "ev.db")
    result = aggregate_reactions(db)
    assert result["n_resolved"] == 0
    assert result["n_pending"] == 0
    assert result["by_event_type"] == {}
    assert result["latency_minutes"] == {"n": 0, "mean": None, "median": None}


def test_aggregate_reactions_always_marks_1h_not_measurable(tmp_path):
    db = str(tmp_path / "ev.db")
    result = aggregate_reactions(db)
    assert result["1h"] == {"measurable": False, "reason": ONE_HOUR_NOT_MEASURABLE_REASON}


def test_aggregate_reactions_computes_mean_and_hit_rate_per_type_and_window(tmp_path):
    db = str(tmp_path / "ev.db")
    queue_pending_reactions(
        db,
        [
            _event(event_key="k1", event_type="beat", ticker="AAA"),
            _event(event_key="k2", event_type="beat", ticker="BBB"),
            _event(event_key="k3", event_type="miss", ticker="CCC"),
        ],
    )
    resolve_reaction(db, "k1", ret_1d=0.02, ret_5d=0.10)
    resolve_reaction(db, "k2", ret_1d=-0.01, ret_5d=0.04)
    resolve_reaction(db, "k3", ret_1d=0.03, ret_5d=-0.06)

    result = aggregate_reactions(db)
    assert result["n_resolved"] == 3
    assert result["n_pending"] == 0

    beat_5d = result["by_event_type"]["beat"]["5d"]
    assert beat_5d["n"] == 2
    assert beat_5d["mean_return"] == 0.07  # mean(0.10, 0.04)
    assert beat_5d["hit_rate"] == 1.0  # both positive

    beat_1d = result["by_event_type"]["beat"]["1d"]
    assert beat_1d["hit_rate"] == 0.5  # one positive (0.02), one negative (-0.01)

    miss_5d = result["by_event_type"]["miss"]["5d"]
    assert miss_5d["n"] == 1
    assert miss_5d["mean_return"] == -0.06
    assert miss_5d["hit_rate"] == 0.0


def test_aggregate_reactions_counts_pending_separately_from_resolved(tmp_path):
    db = str(tmp_path / "ev.db")
    queue_pending_reactions(db, [_event(event_key="k1"), _event(event_key="k2", ticker="MSFT")])
    resolve_reaction(db, "k1", ret_1d=0.01, ret_5d=0.02)
    result = aggregate_reactions(db)
    assert result["n_resolved"] == 1
    assert result["n_pending"] == 1


def test_aggregate_reactions_latency_mean_and_median(tmp_path):
    db = str(tmp_path / "ev.db")
    queue_pending_reactions(
        db,
        [
            _event(event_key="k1", published_at="2026-01-05T08:00:00+00:00"),  # 60 min
            _event(event_key="k2", published_at="2026-01-05T08:30:00+00:00"),  # 30 min
            _event(event_key="k3", published_at=None),  # excluded — unknown latency
        ],
    )
    result = aggregate_reactions(db)
    assert result["latency_minutes"] == {"n": 2, "mean": 45.0, "median": 45.0}
