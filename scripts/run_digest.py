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
from datetime import datetime, timedelta, timezone

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
from equity_scout.state_storage import get_state, set_state
from equity_scout.telegram_client import (
    TelegramError,
    load_telegram_config,
    send_long_message,
)

OPPORTUNITY_TOP_N = 3
EARNINGS_LOOKAHEAD_DAYS = 7  # "diese Woche" — matches the daily digest's own cadence
DIGEST_SENT_KEY = "digest_sent_on"


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


def collect_sector_line(panel) -> str | None:
    """Top-3 sector head line from the shared ETF panel snapshot; None when the panel
    is missing or predates the sector-ETF extension (honest absence, no fetch here)."""
    try:
        if panel is None:
            return None
        return top_sector_line(sector_momentum(panel))
    except Exception:  # noqa: BLE001 - head line is best-effort by design
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--force", action="store_true", help="send even if a digest already went out today"
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    date_label = now.date().isoformat()

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

    def render(html: bool) -> str:
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
            below_threshold=below_threshold,
            html=html,
        )

    text = render(html=False)
    # Marker set right after each successful send (not collected into a `delivered` flag
    # for later): if SMTP goes out and then render(html=True) or the Telegram call raises
    # something other than TelegramError, a marker set only at the end would be lost and
    # the next run would double-send the channel that already succeeded.
    if smtp_config is not None:
        send_digest(smtp_config, f"Copilot-Digest {date_label}", text)
        set_state(args.db, key=DIGEST_SENT_KEY, value=date_label)
    if tg_config is not None:
        try:
            send_long_message(
                tg_config["token"], tg_config.get("daily_chat_id", tg_config["chat_id"]),
                render(html=True), parse_mode="HTML",
            )
            set_state(args.db, key=DIGEST_SENT_KEY, value=date_label)
        except TelegramError as err:
            print(f"Warnung: Telegram-Digest-Versand fehlgeschlagen: {err}", file=sys.stderr)
    if not configured:
        print(text)
        print("Neither SMTP nor Telegram configured — printing digest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
