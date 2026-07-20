"""Digest CLI: inbox pitches -> daily German digest, delivered where configured.

Usage:
    python scripts/run_digest.py [--db equity_scout.db]

Delivery is additive and fail-safe: SMTP e-mail if SMTP_* env is set, Telegram
daily chat if COPILOT_TG_* env is set (channel split 2026-07-14), stdout when
neither is configured — an unconfigured digest is not an error.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np

from equity_scout.autotrader_storage import (
    DEFAULT_AUTOTRADER_DB_PATH,
    load_depot,
    load_risk_events,
    load_trades,
    load_valuations,
)
from equity_scout.promotion import lane_promotion_status
from equity_scout.shortterm_storage import DEFAULT_SHORTTERM_DB_PATH, LANE_LABELS, LANES
from equity_scout.shortterm_storage import load_book as load_st_book
from equity_scout.shortterm_storage import load_trades as load_st_trades
from equity_scout.shortterm_storage import load_valuations as load_st_valuations
from equity_scout.butler import (
    MONTH_NAMES,
    build_core_plan,
    core_running_line,
    monthly_budget,
    render_core_block,
)
from equity_scout.charts import fetch_year_closes
from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.data.etf_panel import DEFAULT_SNAPSHOT, load_snapshot
from equity_scout.digest import build_digest, load_smtp_config, send_digest
from equity_scout.earnings_storage import earnings_within
from equity_scout.evidence.ledger import stats_by_source
from equity_scout.evidence.storage import load_alerts
from equity_scout.inbox_storage import load_pitches
from equity_scout.notify import DEFAULT_THRESHOLD
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.regime import build_regime
from equity_scout.sectors import sector_breadth, sector_momentum, top_sector_line
from equity_scout.state_storage import get_state, record_heartbeat, set_state
from equity_scout.telegram_client import (
    TelegramError,
    load_telegram_config,
    send_long_message,
)

OPPORTUNITY_TOP_N = 3
EARNINGS_LOOKAHEAD_DAYS = 7  # "diese Woche" — matches the daily digest's own cadence
DIGEST_SENT_KEY = "digest_sent_on"
PENDING_TEXT_KEY = "digest_pending_text"
PENDING_DATE_KEY = "digest_pending_date"
PENDING_CORE_MONTH_KEY = "digest_pending_core_month"
CORE_PLAN_MONTH_KEY = "core_plan_month"


def should_skip_send(last_sent: str | None, *, today: str, force: bool, configured: bool) -> bool:
    """True when a configured digest already went out today (v9 idempotency: three
    schedulers may call the chain; the guard makes a second same-day run a no-op)."""
    return configured and not force and last_sent == today


def _closes(ticker: str) -> list[float] | None:
    """1y of closes via the chart seam; any failure is an honest None (regime degrades)."""
    try:
        cached = fetch_year_closes(ticker)
    except Exception:  # noqa: BLE001 - head line is best-effort by design
        return None
    if cached is None:
        return None
    _, closes = cached
    return list(closes) or None


def _last(closes: list[float] | None) -> float | None:
    return closes[-1] if closes else None


def _load_panel():
    """The shared ETF panel snapshot, or None (missing/broken — head lines degrade)."""
    try:
        if not os.path.exists(DEFAULT_SNAPSHOT):
            return None
        return load_snapshot(DEFAULT_SNAPSHOT)
    except Exception:  # noqa: BLE001 - head line is best-effort by design
        return None


def collect_regime(panel) -> dict | None:
    """v8 market head: trend (SPY vs. 200d), VIX band, yield curve (^TNX−^IRX), plus
    the sector-ETF breadth approximation from the local panel (labelled as such).
    Returns None when the composite is unknown (fewer than 3 signals had data)."""
    try:
        breadth = sector_breadth(panel) if panel is not None else None
    except Exception:  # noqa: BLE001
        breadth = None
    regime = build_regime(
        spy_closes=_closes("SPY"),
        vix_level=_last(_closes("^VIX")),
        pct_above_200d=breadth,
        yield_10y=_last(_closes("^TNX")),
        yield_3m=_last(_closes("^IRX")),
        breadth_subject="Sektoren",
    )
    return None if regime["level"] == "unknown" else regime


def _stale_days(last_date: str, today: str, *, trading_days: bool) -> int | None:
    """Age of a block's data (v12 R7, review 2026-07-20): business-day gap for stock books
    (weekend-safe; holidays ignored — conservative), calendar days for 24/7 books.
    None while fresh — the digest only warns, it never guesses."""
    try:
        if trading_days:
            gap = int(np.busday_count(last_date, today))
            return gap if gap > 2 else None
        gap = (date.fromisoformat(today) - date.fromisoformat(last_date)).days
        return gap if gap > 1 else None
    except Exception:  # noqa: BLE001 - malformed dates must not break the digest
        return None


def collect_autodepot(
    db_path: str = DEFAULT_AUTOTRADER_DB_PATH, *, today: str | None = None
) -> dict | None:
    """v10 Auto-Depot block: latest valuation + that date's trades and risk events, plus
    the account's allocation mode and breaker stage. None while no depot exists (honest
    absence) or on any storage error — the digest never fails over its newest section."""
    try:
        account = load_depot(db_path)
        valuations = load_valuations(db_path)
        if account is None or not valuations:
            return None
        last = valuations[-1]
        as_of = last["created_at"]
        today = today or datetime.now(timezone.utc).date().isoformat()
        stale = _stale_days(as_of[:10], today, trading_days=True)
        # day P&L: newest valuation vs the one before it (the depot advances once per
        # trading day, so "previous row" IS the previous trading day)
        day_pnl = day_return = None
        if len(valuations) >= 2:
            prev = valuations[-2]
            day_pnl = last["equity"] - prev["equity"]
            if prev["equity"] > 0:
                day_return = last["equity"] / prev["equity"] - 1.0
        block = {
            "as_of": as_of,
            "day_pnl": day_pnl,
            "day_return": day_return,
            "equity": last["equity"],
            "equity_eur": last["equity_eur"],
            "total_return": last["total_return"],
            "benchmark_return": last["benchmark_return"],
            "gross_exposure": last["gross_exposure"],
            "drawdown": last["drawdown"],
            "mode": account.sleeve_mode,
            "breaker_stage": account.breaker.stage,
            "trades": [t for t in load_trades(db_path, limit=50) if t["created_at"] == as_of],
            "risk_events": [
                e["detail"] for e in load_risk_events(db_path, limit=20)
                if e["created_at"] == as_of
            ],
        }
        if stale is not None:
            block["stale_days"] = stale
        return block
    except Exception:  # noqa: BLE001 - best-effort section by design
        return None


_LANE_LABELS = LANE_LABELS


def collect_shortterm(
    today: str, db_path: str = DEFAULT_SHORTTERM_DB_PATH,
    *, promoted: frozenset[str] = frozenset(),
) -> list[dict] | None:
    """v11 arena block: one line per started lane (return, benchmark, today's fills).
    None while no lane has data — honest absence, and errors never break the digest."""
    try:
        lanes = []
        for lane in LANES:
            book = load_st_book(db_path, lane)
            vals = load_st_valuations(db_path, lane)
            if book is None or not vals:
                continue
            latest = vals[-1]
            trades_today = sum(
                1 for t in load_st_trades(db_path, lane, limit=100)
                if t["executed_at"][:10] == today
            )
            # day P&L baseline: the last valuation BEFORE today (the intraday lanes write
            # several rows per day); a lane that started today measures from its capital.
            prior = [v for v in vals if v["created_at"][:10] < today]
            baseline = prior[-1]["equity"] if prior else book.initial_capital
            stale = _stale_days(
                latest["created_at"][:10], today, trading_days=lane != "crypto"
            )
            status = lane_promotion_status(
                load_st_trades(db_path, lane, limit=5000), vals, today=today
            )
            lanes.append({
                "lane": lane,
                "label": _LANE_LABELS.get(lane, lane),
                "total_return": latest["total_return"],
                "day_pnl": latest["equity"] - baseline,
                "benchmark_ticker": book.benchmark_ticker,
                "benchmark_return": latest["benchmark_return"],
                "trades_today": trades_today,
                "promoted": lane in promoted,
                "promotion": status,
                **({"stale_days": stale} if stale is not None else {}),
            })
        return lanes or None
    except Exception:  # noqa: BLE001 - best-effort section by design
        return None


def collect_sector_line(panel) -> str | None:
    """Top-3 sector head line from the shared ETF panel snapshot; None when the panel
    is missing or predates the sector-ETF extension (honest absence, no fetch here)."""
    try:
        if panel is None:
            return None
        return top_sector_line(sector_momentum(panel))
    except Exception:  # noqa: BLE001 - head line is best-effort by design
        return None


def store_pending(
    db: str, *, date_label: str, html_text: str, core_month: str | None
) -> None:
    set_state(db, key=PENDING_DATE_KEY, value=date_label)
    set_state(db, key=PENDING_TEXT_KEY, value=html_text)
    set_state(db, key=PENDING_CORE_MONTH_KEY, value=core_month or "")


def clear_pending(db: str) -> None:
    set_state(db, key=PENDING_DATE_KEY, value="")
    set_state(db, key=PENDING_TEXT_KEY, value="")
    set_state(db, key=PENDING_CORE_MONTH_KEY, value="")


def maybe_resend_pending(db: str, *, now: datetime | None = None) -> bool:
    """Retry a digest whose Telegram send failed (v12 R6, review 2026-07-20): called first
    by the digest run AND the */15 notify chain, so one network blip at 18:05 no longer
    kills the day's digest. Same-day only — a pending from yesterday is a stale snapshot
    and is dropped, not sent."""
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    pending_date = get_state(db, key=PENDING_DATE_KEY)
    if not pending_date:
        return False
    text = get_state(db, key=PENDING_TEXT_KEY)
    if pending_date != today or not text:
        clear_pending(db)
        return False
    tg_config = load_telegram_config(dict(os.environ))
    if tg_config is None:
        return False
    try:
        send_long_message(
            tg_config["token"], tg_config.get("daily_chat_id", tg_config["chat_id"]),
            text, parse_mode="HTML",
        )
    except TelegramError as err:
        print(f"Warnung: Digest-Nachversand fehlgeschlagen: {err}", file=sys.stderr)
        return False
    set_state(db, key=DIGEST_SENT_KEY, value=pending_date)
    core_month = get_state(db, key=PENDING_CORE_MONTH_KEY)
    if core_month:
        set_state(db, key=CORE_PLAN_MONTH_KEY, value=core_month)
    clear_pending(db)
    print(f"Digest für {pending_date} nachversendet.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--force", action="store_true", help="send even if a digest already went out today"
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    date_label = now.date().isoformat()

    maybe_resend_pending(args.db, now=now)

    # Guard first, before the expensive digest data collection: a skipped second run
    # should cost nothing.
    smtp_config = load_smtp_config(dict(os.environ))
    tg_config = load_telegram_config(dict(os.environ))
    configured = smtp_config is not None or tg_config is not None
    if should_skip_send(
        get_state(args.db, key=DIGEST_SENT_KEY),
        today=date_label, force=args.force, configured=configured,
    ):
        print(f"Digest für {date_label} bereits verschickt — übersprungen (--force erzwingt).")
        record_heartbeat(args.db, "daily", now=now.isoformat())
        return 0

    day_ago = (now - timedelta(hours=24)).isoformat(timespec="seconds")

    # limit=1000: don't let load_pitches' default cap (100) silently drop open pitches
    # from a DAILY digest; the decided section is scoped to the last 24h instead.
    pitches = load_pitches(args.db, limit=1000)
    alerts_today = [a for a in load_alerts(args.db, limit=50) if a["created_at"] >= day_ago]
    watchlist = load_latest_watchlist(args.db) or {}
    opportunities = sorted(
        watchlist.get("entries", []), key=lambda e: e["composite"], reverse=True
    )[:OPPORTUNITY_TOP_N]
    earnings_this_week = earnings_within(
        args.db, today=date_label, days=EARNINGS_LOOKAHEAD_DAYS
    )

    below_threshold = sum(
        1 for entry in watchlist.get("entries", []) if entry["composite"] < DEFAULT_THRESHOLD
    )
    panel = _load_panel()
    regime = collect_regime(panel)
    sector_line = collect_sector_line(panel)
    evidence_stats = stats_by_source(args.db)
    autodepot = collect_autodepot(today=date_label)
    depot_account = load_depot(DEFAULT_AUTOTRADER_DB_PATH)
    promoted = frozenset(depot_account.promoted_lanes) if depot_account else frozenset()
    shortterm = collect_shortterm(date_label, promoted=promoted)

    # v9 butler: full savings-plan block once per month, one-liner on the other days.
    # No panel / strategy silent -> no block at all (honest absence), and the month
    # marker is only set after a successful send so a failed run retries tomorrow.
    month_key = date_label[:7]
    core_sent_this_month = get_state(args.db, key=CORE_PLAN_MONTH_KEY) == month_key
    core_plan = None
    if not core_sent_this_month:
        core_plan = build_core_plan(panel, monthly_budget_eur=monthly_budget(dict(os.environ)))

    def render(html: bool) -> str:
        if core_plan is not None:
            month_label = MONTH_NAMES[int(date_label[5:7]) - 1]
            core_block = render_core_block(core_plan, month_label=month_label, html=html)
        elif core_sent_this_month:
            core_block = core_running_line(html=html)
        else:
            core_block = None
        return build_digest(
            pitches,
            date_label=date_label,
            decided_since=day_ago,
            evidence_stats=evidence_stats,
            alerts_today=alerts_today,
            opportunities=opportunities,
            earnings_this_week=earnings_this_week,
            regime=regime,
            sector_line=sector_line,
            core_block=core_block,
            below_threshold=below_threshold,
            autodepot=autodepot,
            shortterm=shortterm,
            html=html,
        )

    def mark_sent() -> None:
        set_state(args.db, key=DIGEST_SENT_KEY, value=date_label)
        if core_plan is not None:
            set_state(args.db, key=CORE_PLAN_MONTH_KEY, value=month_key)

    text = render(html=False)
    # Marker set right after each successful send (not collected into a `delivered` flag
    # for later): if SMTP goes out and then render(html=True) or the Telegram call raises
    # something other than TelegramError, a marker set only at the end would be lost and
    # the next run would double-send the channel that already succeeded.
    if smtp_config is not None:
        send_digest(smtp_config, f"Copilot-Digest {date_label}", text)
        mark_sent()
    if tg_config is not None:
        html_text = render(html=True)
        try:
            send_long_message(
                tg_config["token"], tg_config.get("daily_chat_id", tg_config["chat_id"]),
                html_text, parse_mode="HTML",
            )
            mark_sent()
        except TelegramError as err:
            store_pending(
                args.db, date_label=date_label, html_text=html_text,
                core_month=month_key if core_plan is not None else None,
            )
            print(
                f"Warnung: Telegram-Digest-Versand fehlgeschlagen — wird beim nächsten "
                f"Chain-Lauf nachversendet: {err}",
                file=sys.stderr,
            )
    if not configured:
        print(text)
        print("Neither SMTP nor Telegram configured — printing digest.")
    record_heartbeat(args.db, "daily", now=now.isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
