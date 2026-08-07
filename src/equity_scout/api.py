"""API for the dashboard. Serves the latest run snapshot + strategy reports + disclaimer,
plus the decision inbox (GET listing, POST one-tap buy/pass/later decisions)."""
from __future__ import annotations

import hmac
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from equity_scout.briefs import (
    analyst_upside_pct,
    build_brief,
    pitch_market_context,
    rank_entries,
)
from equity_scout.buckets import BUCKET_WEIGHTS
from equity_scout.constants import (
    DEFAULT_CACHE_DB_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_FORWARD_DB_PATH,
    DISCLAIMER,
    ML_SLEEVE_NAMES,
    MODEL_CAVEATS,
)
from equity_scout.promotion import lane_promotion_status
from equity_scout.shortterm_book import position_targets
from equity_scout.proof import (
    CONVICTION_THRESHOLDS,
    MIN_DAYS_FOR_RATES,
    collect_proof_books,
)
from equity_scout.data.etf_panel import DEFAULT_SNAPSHOT, load_snapshot
from equity_scout.evidence.event_reactions import aggregate_reactions
from equity_scout.evidence.ledger import stats_by_source
from equity_scout.evidence.person_storage import load_person_scores
from equity_scout.evidence.storage import events_in_window, load_alerts
from equity_scout.autotrader_storage import (
    DEFAULT_AUTOTRADER_DB_PATH,
    load_latest_sleeve_weights,
)
from equity_scout.autotrader_storage import load_depot as load_autotrader_depot
from equity_scout.autotrader_storage import load_risk_events as load_autotrader_risk_events
from equity_scout.autotrader_storage import load_trades as load_autotrader_trades
from equity_scout.autotrader_storage import load_valuations as load_autotrader_valuations
from equity_scout.forward_storage import load_all_accounts
from equity_scout.forward_storage import load_valuations as load_forward_valuations
from equity_scout.fundamentals import fetch_fundamentals_cached
from equity_scout.shortterm_book import stats as shortterm_stats
from equity_scout.shortterm_storage import (
    DEFAULT_SHORTTERM_DB_PATH,
    LANE_LABELS,
    LANES,
)
from equity_scout.shortterm_storage import get_lane_state as get_st_lane_state
from equity_scout.shortterm_storage import load_book as load_st_book
from equity_scout.shortterm_storage import load_trades as load_st_trades
from equity_scout.shortterm_storage import load_valuations as load_st_valuations
from equity_scout.inbox_storage import decide_pitch, get_pitch, load_pitches
from equity_scout.insights_storage import load_insights, load_price_series
from equity_scout.lane_storage import (
    load_lane_portfolio,
    load_lane_trades,
    load_lane_valuations,
)
from equity_scout.lanes import LANE_AUTOPILOT, LANE_NICO
from equity_scout.logos import ensure_logo
from equity_scout.portfolio_storage import load_portfolio, load_valuations
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.sectors import sector_momentum
from equity_scout.storage import (
    init_db,
    latest_run_id,
    load_latest_run,
    load_run_scores,
    load_run_summaries,
    run_has_scores,
    run_scores_facets,
)
from equity_scout.universe import REGION_GROUPS
from equity_scout.telegram_client import ACTIONS
from equity_scout.ml.ledger import DEFAULT_LEDGER_PATH, champion
from equity_scout.ml.learning_curve import load_daily_curve
from equity_scout.ml.model_registry import entry_champion, load_champion_history, registry_summary
from equity_scout.ml.prediction_ledger import (
    drift_snapshot,
    latest_scores,
    recent_prediction_features,
    resolved_stats,
    resolved_stats_windowed,
)
from equity_scout.ml.research_view import research_summary
from equity_scout.strategy_service import BENCHMARK_NAME, build_ml_report, build_reports

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

# Evidence window for the assistant. The dashboard shows 30 days; congress filings
# arrive with a measured p99 lag of 261 days (v15-P2a backfill), so "wer hat gekauft"
# needs a window that outlives the paperwork.
_CHAT_EVIDENCE_WINDOW_DAYS = 400

# Dossiers per question. Four covers "vergleiche A, B und C" without letting one
# message drag the whole watchlist into a 7B model's context.
_CHAT_MAX_DOSSIERS = 4


FILTER_TOP_N = 10


def _filtered_buckets(
    db_path: str, *, region: str | None, country: str | None, sector: str | None
) -> dict:
    """Filtered view over the latest run's persisted full ranking.

    Returns Pick-shaped dicts so the dashboard renders filtered results with the exact
    same components as the default view. Region accepts a group name ('europe') or a
    single region code; ranks are re-numbered within the filtered set."""
    echo = {"region": region, "country": country, "sector": sector}
    run_id = latest_run_id(db_path)
    if run_id is None or not run_has_scores(db_path, run_id):
        return {"filters": echo, "filter_unavailable": True}

    region_codes: set[str] | None = None
    if region:
        region_codes = REGION_GROUPS.get(region.lower(), {region.upper()})
    rows = load_run_scores(
        db_path, run_id, region_codes=region_codes,
        country=country.upper() if country else None, sector=sector,
    )
    buckets: dict[str, list[dict]] = {b: [] for b in BUCKET_WEIGHTS}
    for row in rows:  # ordered by bucket, global rank
        picks = buckets.setdefault(row["bucket"], [])
        if len(picks) >= FILTER_TOP_N:
            continue
        picks.append({
            "instrument": {"ticker": row["ticker"], "name": row["name"], "exchange": "",
                           "region": row["region"], "currency": "",
                           "sector": row["sector"]},
            "bucket": row["bucket"], "rank": len(picks) + 1,
            "composite": row["composite"], "breakdown": row["breakdown"],
            "thesis": None, "news": [],
        })
    return {"filters": echo, "filter_matches": len(rows), "buckets": buckets}


def _known_company_names(db_path: str) -> dict[str, str]:
    """{ticker: name} from what this machine already knows — the newest watchlist snapshot
    and the latest run's persisted ranking.

    Deliberately no yfinance lookup: a request must never wait on the network for a label
    (the 6 h cache in fundamentals.py exists for exactly this reason). A ticker missing here
    stays nameless rather than guessed.
    """
    names: dict[str, str] = {}
    run_id = latest_run_id(db_path)
    if run_id is not None and run_has_scores(db_path, run_id):
        for row in load_run_scores(db_path, run_id):
            if row.get("name"):
                names[row["ticker"]] = row["name"]
    watchlist = load_latest_watchlist(db_path)
    # Watchlist last: it is the fresher of the two for the tickers it covers.
    for entry in (watchlist or {}).get("entries", []):
        if entry.get("name"):
            names[entry["ticker"]] = entry["name"]
    return names


# The chat lexicon spans EVERY run, not just the latest (a question about a dropped title
# is legitimate), and rebuilding its ~20 000-key index on every message would be wasted
# work: it only changes when a scout run writes new rows.
_CHAT_LEXICON_TTL_SECONDS = 600
_chat_lexicon_cache: dict[str, tuple[float, dict[str, str], dict[str, str]]] = {}


def _chat_lexicon(db_path: str, *, now: float | None = None) -> tuple[dict, dict]:
    """(lexicon, lookup) for ticker detection, cached per DB path for 10 minutes."""
    from equity_scout.chat_retrieval import build_lookup
    from equity_scout.storage import load_company_names

    stamp = time.monotonic() if now is None else now
    hit = _chat_lexicon_cache.get(db_path)
    if hit is not None and stamp - hit[0] < _CHAT_LEXICON_TTL_SECONDS:
        return hit[1], hit[2]
    lexicon = load_company_names(db_path)
    for ticker, name in _known_company_names(db_path).items():
        lexicon[ticker] = name  # watchlist names win — they are the freshest
    lookup = build_lookup(lexicon)
    _chat_lexicon_cache[db_path] = (stamp, lexicon, lookup)
    return lexicon, lookup


def _chat_inbox_block(pitches: list[dict]) -> str:
    """Open pitches, one line each — the block behind "Warum wurde Yamato nicht gekauft?"."""
    from equity_scout.chat_retrieval import _STATUS_DE

    open_rows = [p for p in pitches if p["status"] == "open"]
    lines = ["INBOX (Pitches, die auf Nicos Entscheidung warten):"]
    if not open_rows:
        lines.append("- Keine offenen Pitches.")
    for p in open_rows[:10]:
        lines.append(
            f"- {p['ticker']}: Score {round(p['composite'] * 100)}/100, "
            f"Pitch vom {p['created_at'][:10]}, Status offen."
        )
    for p in [p for p in pitches if p["status"] != "open"][:5]:
        lines.append(
            f"- {p['ticker']}: Status {_STATUS_DE.get(p['status'], p['status'])} "
            f"am {(p['decided_at'] or '?')[:10]}."
        )
    return "\n".join(lines)


def _chat_depots_block(db_path: str, autotrader_db: str, shortterm_db: str) -> str:
    """Both depots and the arena lanes with their positions — "was halte ich eigentlich?"."""
    lines = ["DEPOTS (Paper-Trading, kein echtes Geld):"]
    for lane, label in ((LANE_NICO, "Depot 'Du'"), (LANE_AUTOPILOT, "Depot 'Autopilot'")):
        portfolio = load_lane_portfolio(db_path, lane)
        if portfolio is None:
            lines.append(f"- {label}: noch nicht eingerichtet.")
            continue
        held = [
            f"{ticker} {round(pos.shares, 2)} Anteile"
            for ticker, pos in sorted(portfolio.positions.items())
        ]
        lines.append(
            f"- {label}: Barbestand {round(portfolio.cash, 2)}, "
            f"{('Positionen: ' + ', '.join(held)) if held else 'keine Positionen'}."
        )
    account = load_autotrader_depot(autotrader_db)
    vals = load_autotrader_valuations(autotrader_db)
    if account is not None and vals:
        last = vals[-1]
        lines.append(
            f"- Auto-Depot (automatisch, Regel- und ML-Sleeves): Wert {round(last['equity'], 2)}, "
            f"Gesamtrendite {last['total_return'] * 100:+.1f} %, Stand {last['created_at'][:10]}."
        )
    else:
        lines.append("- Auto-Depot: noch keine Bewertung im Bestand.")
    for lane in LANES:
        book = load_st_book(shortterm_db, lane)
        lane_vals = load_st_valuations(shortterm_db, lane)
        if book is None or not lane_vals:
            continue
        latest = lane_vals[-1]
        positions = ", ".join(sorted(book.positions)) or "flat"
        lines.append(
            f"- Arena {LANE_LABELS.get(lane, lane)}: Wert {round(latest['equity'], 2)}, "
            f"{latest['total_return'] * 100:+.1f} %, aktuell {positions}."
        )
    return "\n".join(lines)


def _chat_proof_block(autotrader_db: str, shortterm_db: str, forward_db: str) -> str:
    """The report cards — "funktioniert das überhaupt?" answered with measured numbers."""
    books = collect_proof_books(autotrader_db, shortterm_db, forward_db)
    if not books:
        return "ERGEBNISSE: noch keine bewertbaren Bücher."
    lines = [
        f"ERGEBNISSE (gemessen, nach Kosten; ein Urteil braucht {MIN_DAYS_FOR_RATES} Tage):"
    ]
    for book in books:
        report = book.get("report") or {}
        verdict = report.get("verdict") or "noch kein Urteil"
        parts = [f"{book.get('label', book.get('key'))}: {verdict}"]
        for key, label in (("total_return", "Gesamtrendite"), ("sharpe", "Sharpe"),
                           ("max_drawdown", "größter Rückgang"), ("win_rate", "Trefferquote")):
            value = report.get(key)
            if value is None:
                continue
            parts.append(
                f"{label} {value * 100:+.1f} %" if key != "sharpe" else f"{label} {value:.2f}"
            )
        days = report.get("days")
        if days is not None:
            parts.append(f"{days} Tage Historie")
        lines.append("- " + ", ".join(parts) + ".")
    return "\n".join(lines)


def _chat_people_block(db_path: str, now: str) -> str:
    """Who has been buying across ALL tickers — the "was hat Person X gekauft" direction.

    Window is 400 days, not the dashboard's 30: congress filings arrive with a measured
    p99 lag of 261 days, so a month-long window answers "wer hat gekauft" with silence.
    """
    from equity_scout.chat_retrieval import (
        _CHAMBER_DE,
        _PARTY_DE,
        _UNKNOWN_CHAMBER,
        _UNKNOWN_PARTY,
    )

    grouped = events_in_window(db_path, window_days=_CHAT_EVIDENCE_WINDOW_DAYS, now=now)
    congress: list[tuple[str, str, dict]] = []
    voices: list[tuple[str, str, dict]] = []
    funds: list[tuple[str, str, dict]] = []
    for ticker, events in grouped.items():
        for event in events:
            bucket = {"congress": congress, "voice": voices,
                      "thirteen_f": funds}.get(event["source"])
            if bucket is not None:
                bucket.append((ticker, event["event_date"], event["details"]))
    lines = [f"PERSONEN (gemeldete Käufe und Stimmen der letzten "
             f"{_CHAT_EVIDENCE_WINDOW_DAYS} Tage):"]
    congress.sort(key=lambda row: row[1], reverse=True)
    if congress:
        # Grouped by person, not by date: one backfill drops hundreds of filings with the
        # SAME filing date, so a date-sorted list answers "welche Mitglieder haben gekauft"
        # with the same name twelve times.
        by_person: dict[str, list[tuple[str, str, dict]]] = {}
        for row in congress:
            by_person.setdefault(str(row[2].get("politician") or "unbekannt"), []).append(row)
        ranked = sorted(by_person.items(), key=lambda kv: -len(kv[1]))
        lines.append(
            f"- Offenlegungen (Kongress und Regierung): {len(congress)} gemeldete Käufe "
            f"von {len(by_person)} Personen. Die aktivsten:"
        )
        for person, rows in ranked[:10]:
            newest_ticker, newest_date, d = rows[0]
            party = _PARTY_DE.get(str(d.get("party") or ""), d.get("party") or _UNKNOWN_PARTY)
            chamber = _CHAMBER_DE.get(str(d.get("chamber") or ""), _UNKNOWN_CHAMBER)
            lag = d.get("days_to_file")
            others = sorted({row[0] for row in rows[1:]})[:6]
            lines.append(
                f"  · {person} ({party}, {chamber}): {len(rows)} Käufe, zuletzt "
                f"{newest_ticker} (gekauft {d.get('transaction_date', '?')}, gemeldet "
                f"{newest_date}{f', {lag} Tage Meldeverzug' if lag is not None else ''}, "
                f"Volumen {d.get('amount_range', '?')})"
                f"{'; außerdem ' + ', '.join(others) if others else ''}."
            )
    else:
        lines.append("- Offenlegungen: keine Käufe im Fenster.")
    funds.sort(key=lambda row: row[1], reverse=True)
    for ticker, date, d in funds[:5]:
        lines.append(
            f"- Fonds {d.get('fund', '?')}: {d.get('change', '?')} bei {ticker} "
            f"(Quartalsende {d.get('period', '?')}, gemeldet {date})."
        )
    voices.sort(key=lambda row: row[1], reverse=True)
    for ticker, date, d in voices[:5]:
        lines.append(f"- Stimme {d.get('speaker', '?')} zu {ticker} am {date}.")
    scores = load_person_scores(db_path)
    scored = [s for s in scores if s.get("scoreable")]
    if scored:
        lines.append("- Gemessene Trefferquoten (unsere eigene Auswertung):")
        for s in scored[:8]:
            rate = s.get("hit_rate_short")
            lines.append(
                f"  · {s['person']} ({s['source']}): {s['n_calls']} Käufe, "
                f"Trefferquote kurzfristig "
                f"{'—' if rate is None else f'{rate * 100:.0f} %'}."
            )
    return "\n".join(lines)


def _chat_regime_block(cached: object) -> str:
    """Market traffic light from the per-day cache only.

    Deliberately never computes: /api/regime pulls SPY/VIX/yields from yfinance, and a
    chat message must not trigger three network fetches. The dashboard warms this cache
    on every app open, so in practice it is there.
    """
    payload = cached.get("payload", {}) if isinstance(cached, dict) else {}
    regime = payload.get("regime") if isinstance(payload, dict) else None
    if not isinstance(regime, dict):
        return "MARKTLAGE: heute noch nicht abgerufen (die Ampel lädt beim Öffnen der App)."
    lines = [
        f"MARKTLAGE (Ampel aus {regime.get('available', '?')} auswertbaren Signalen): "
        f"{regime.get('label', '?')}, {regime.get('green_count', '?')} davon grün."
    ]
    for signal in regime.get("signals", []) or []:
        state = {True: "grün", False: "nicht grün", None: "nicht auswertbar"}[
            signal.get("green")
        ]
        lines.append(f"- {signal.get('label', '?')}: {state} ({signal.get('note', '')})")
    return "\n".join(lines)


def create_app(
    db_path: str = DEFAULT_DB_PATH,
    snapshot: str = DEFAULT_SNAPSHOT,
    ledger: str = DEFAULT_LEDGER_PATH,
    forward_db: str = DEFAULT_FORWARD_DB_PATH,
    autotrader_db: str = DEFAULT_AUTOTRADER_DB_PATH,
    shortterm_db: str = DEFAULT_SHORTTERM_DB_PATH,
    cache_db: str = DEFAULT_CACHE_DB_PATH,
    dash_token: str | None = None,
    warm_model: bool = False,
) -> FastAPI:
    # The read API may face a DB written before a schema migration (e.g. the
    # data_quality column); init_db is idempotent and carries the migrations.
    init_db(db_path)
    app = FastAPI(title="equity-scout")

    if warm_model:
        # Pull the chat model into RAM in the background: the first question of the day
        # otherwise pays a measured 90-120 s cold start (2026-08-07 eval). Off by default
        # so no test ever touches Ollama; scripts/run_api.py turns it on.
        import threading

        from equity_scout.chat import warm_model as _warm

        threading.Thread(target=_warm, daemon=True).start()

    # v12 M1: shared-secret gate for the phone cockpit. With DASH_TOKEN set, every
    # non-loopback request (static app included — the whole dashboard is private) must
    # carry the token: `?token=` once (persisted as a cookie), the X-Dash-Token header,
    # or the cookie. Threat model is the home LAN, not the internet — one secret, no
    # user system. Without a token the app is loopback-only (run_api.py refuses to
    # bind wider), so nothing is ever newly exposed without auth.
    token = os.environ.get("DASH_TOKEN", "") if dash_token is None else dash_token

    @app.middleware("http")
    async def _token_gate(request, call_next):  # noqa: ANN001, ANN202
        if not token:
            return await call_next(request)
        client_host = request.client.host if request.client else ""
        if client_host in ("127.0.0.1", "::1"):
            return await call_next(request)
        supplied = (
            request.query_params.get("token")
            or request.headers.get("x-dash-token")
            or request.cookies.get("es_dash")
            or ""
        )
        if not hmac.compare_digest(supplied, token):
            return JSONResponse({"error": "Nicht autorisiert."}, status_code=401)
        response = await call_next(request)
        if request.query_params.get("token"):
            response.set_cookie(
                "es_dash", token, httponly=True, samesite="lax",
                max_age=180 * 24 * 3600,
            )
        return response
    reports_cache: dict[str, object] = {}  # built once per process (backtests are deterministic)

    def get_reports() -> list | None:
        if "reports" not in reports_cache:
            if not os.path.exists(snapshot):
                return None
            reports_cache["reports"] = build_reports(load_snapshot(snapshot))
        return reports_cache["reports"]

    @app.get("/api/strategies")
    def strategies() -> JSONResponse:
        reports = get_reports()
        if reports is None:
            return JSONResponse({
                "available": False,
                "strategies": [],
                "hint": "Run `python scripts/run_backtest.py --refresh` to fetch the price panel.",
                "disclaimer": DISCLAIMER,
            })
        return JSONResponse({
            "available": True,
            "benchmark": BENCHMARK_NAME,
            "strategies": [asdict(r) for r in reports],
            "disclaimer": DISCLAIMER,
        })

    @app.get("/api/regime")
    def regime() -> JSONResponse:
        """v8 market traffic light. Trend/VIX/curve come from yfinance (one 1y fetch
        each, cached per calendar day so the dashboard never hammers the API); breadth
        is the sector-ETF approximation from the local panel snapshot. Every failed
        input degrades to an honest missing signal — regime.combine needs 3."""
        from datetime import date as _date

        from equity_scout.charts import fetch_year_closes
        from equity_scout.regime import build_regime
        from equity_scout.sectors import sector_breadth

        today = _date.today().isoformat()
        cached = reports_cache.get("regime")
        if isinstance(cached, dict) and cached.get("date") == today:
            return JSONResponse(cached["payload"])

        def closes(ticker: str) -> list[float] | None:
            try:
                fetched = fetch_year_closes(ticker)
            except Exception:  # noqa: BLE001 - each leg degrades independently
                return None
            if fetched is None:
                return None
            return [float(v) for v in fetched[1]] or None

        def last(values: list[float] | None) -> float | None:
            return values[-1] if values else None

        breadth = None
        if os.path.exists(snapshot):
            try:
                breadth = sector_breadth(load_snapshot(snapshot))
            except Exception:  # noqa: BLE001
                breadth = None
        payload = {
            "regime": build_regime(
                spy_closes=closes("SPY"),
                vix_level=last(closes("^VIX")),
                pct_above_200d=breadth,
                yield_10y=last(closes("^TNX")),
                yield_3m=last(closes("^IRX")),
                breadth_subject="Sektoren",
            ),
            "disclaimer": DISCLAIMER,
        }
        reports_cache["regime"] = {"date": today, "payload": payload}
        return JSONResponse(payload)

    @app.get("/api/sectors")
    def sectors() -> JSONResponse:
        """v8 sector momentum snapshot — same panel + return arithmetic the rotation
        strategy trades on. Panels from before the sector-ETF extension simply yield
        rows with null returns (honest absence) until the next --refresh."""
        if "sectors" not in reports_cache:
            if not os.path.exists(snapshot):
                return JSONResponse({"available": False, "sectors": [],
                                     "hint": "Run `python scripts/run_backtest.py --refresh`.",
                                     "disclaimer": DISCLAIMER})
            reports_cache["sectors"] = sector_momentum(load_snapshot(snapshot))
        return JSONResponse({
            "available": True,
            "sectors": reports_cache["sectors"],
            "disclaimer": DISCLAIMER,
        })

    @app.get("/api/ml")
    def ml() -> JSONResponse:
        if not os.path.exists(snapshot):
            return JSONResponse({"available": False, "disclaimer": DISCLAIMER})
        if "ml" not in reports_cache:
            from equity_scout.data.etf_panel import load_snapshot as _load

            # Serve the research loop's current champion config once the search has found one;
            # falls back to the fixed baseline (build_ml_report's default) otherwise.
            record = champion(ledger) if os.path.exists(ledger) else None
            reports_cache["ml"] = build_ml_report(_load(snapshot), record.config if record else None)
        return JSONResponse({"available": True, "report": asdict(reports_cache["ml"]), "disclaimer": DISCLAIMER})

    @app.get("/api/research")
    def research() -> JSONResponse:
        # No cache: reflects the background research loop live as it writes to the ledger.
        return JSONResponse({**research_summary(ledger), "disclaimer": DISCLAIMER})

    def _pick_extras(pick: dict, fundamentals, insights: dict, series: dict) -> dict:
        """Screener-card context per pick (Nico 2026-08-07): the cached insight + own
        chart (nightly run_insights covers the run picks), last close from that chart,
        and the analyst target/upside — no live fetch beyond the shared 6 h cache.
        `year_high_gap_pct` is the honest fallback figure for names without analyst
        coverage: distance to the 52-week high — geometry, labelled as such in the UI,
        never a price target."""
        ticker = pick["instrument"]["ticker"]
        chart = series.get(ticker)
        closes = (chart or {}).get("closes") or []
        last_close = closes[-1] if closes else None
        target = fundamentals.analyst_target if fundamentals else None
        year_high = fundamentals.year_high if fundamentals else None
        return {
            **pick,
            "insight": insights.get(ticker),
            "chart": chart,
            "price": last_close,
            "currency": fundamentals.currency if fundamentals else None,
            "analyst_target": target,
            "analyst_count": fundamentals.analyst_count if fundamentals else None,
            "analyst_upside_pct": (
                analyst_upside_pct(target, last_close) if last_close is not None else None
            ),
            "year_high_gap_pct": (
                analyst_upside_pct(year_high, last_close) if last_close is not None else None
            ),
        }

    @app.get("/api/latest")
    def latest(region: str | None = None, country: str | None = None,
               sector: str | None = None) -> JSONResponse:
        run = load_latest_run(db_path)
        if run is None:
            return JSONResponse({"buckets": {}, "gated_out": {}, "disclaimer": DISCLAIMER})

        def _fundamentals(ticker: str):
            try:
                return fetch_fundamentals_cached(ticker)
            except Exception:  # noqa: BLE001 - one bad ticker must never break the screener
                return None

        buckets = {b: [asdict(p) for p in picks] for b, picks in run.buckets.items()}
        tickers = sorted({p["instrument"]["ticker"] for picks in buckets.values() for p in picks})
        with ThreadPoolExecutor(max_workers=5) as pool:
            by_ticker = dict(zip(tickers, pool.map(_fundamentals, tickers)))
        insights = load_insights(db_path)
        series = load_price_series(db_path)
        payload = {
            "created_at": run.created_at,
            "universe_size": run.universe_size,
            "gated_out": run.gated_out,
            "gate_stats": run.gate_stats,
            "data_quality": run.data_quality,
            "buckets": {
                b: [
                    _pick_extras(p, by_ticker.get(p["instrument"]["ticker"]), insights, series)
                    for p in picks
                ]
                for b, picks in buckets.items()
            },
            "bucket_weights": BUCKET_WEIGHTS,
            "disclaimer": DISCLAIMER,
        }
        if region or country or sector:
            payload.update(
                _filtered_buckets(db_path, region=region, country=country, sector=sector)
            )
        return JSONResponse(payload)

    @app.get("/api/filters")
    def filter_options() -> JSONResponse:
        run_id = latest_run_id(db_path)
        facets = run_scores_facets(db_path, run_id) if run_id is not None else {
            "countries": [], "sectors": []}
        return JSONResponse({"region_groups": sorted(REGION_GROUPS), **facets})

    @app.get("/api/radar")
    def radar() -> JSONResponse:
        # v6 P6: the ML champion score rides along per entry ("Stand: letzter Score-Lauf" from
        # the prediction ledger, never recomputed live). None when the ticker was never scored.
        watchlist = load_latest_watchlist(db_path)
        if watchlist and watchlist.get("entries"):
            scores = latest_scores(db_path)
            entries = watchlist["entries"]

            def _fundamentals(ticker: str):
                try:
                    return fetch_fundamentals_cached(ticker)
                except Exception:  # noqa: BLE001 - one bad ticker must never break the radar
                    return None

            # Analyst potential per entry (Nico 2026-08-07: "bei alle im Radar auch das
            # unterscheiden" — the analyst view next to our model, same split as the Heute
            # list). Cached fundamentals, bounded pool — the same idiom as /api/briefs.
            with ThreadPoolExecutor(max_workers=5) as pool:
                fetched = list(pool.map(_fundamentals, [e["ticker"] for e in entries]))
            for entry, fundamentals in zip(entries, fetched):
                entry["ml"] = scores.get(entry["ticker"])
                target = fundamentals.analyst_target if fundamentals else None
                price = entry["price"]
                entry["analyst_target"] = target
                entry["analyst_count"] = fundamentals.analyst_count if fundamentals else None
                entry["analyst_upside_pct"] = analyst_upside_pct(target, price)
        return JSONResponse({"watchlist": watchlist, "disclaimer": DISCLAIMER})

    @app.get("/api/briefs")
    def briefs(limit: int = 12) -> JSONResponse:
        # Bundles the four things the phone card needs per row — what the company does
        # (sector/industry), whether the price is a good entry (zone verdict), the
        # analyst-consensus upside, KGV — so the frontend does not fan out over
        # /api/radar + /api/entry/{t} + a fundamentals call per row itself.
        limit = max(1, min(limit, 20))
        watchlist = load_latest_watchlist(db_path)
        top = rank_entries((watchlist or {}).get("entries", []))[:limit]

        def _fetch(ticker: str):
            try:
                # Cached: the phone hits this endpoint on every app open, and five live
                # yfinance calls per visit would burn a free rate limit for data that
                # changes quarterly (see fundamentals.FUNDAMENTALS_TTL_SECONDS).
                return fetch_fundamentals_cached(ticker)
            except Exception:  # noqa: BLE001 - one bad ticker must never break the list
                return None

        # yfinance is rate-limited and free: a small pool bounds one slow/hanging
        # ticker's latency instead of serialising up to `limit` sequential network
        # calls into ~20 s.
        with ThreadPoolExecutor(max_workers=5) as pool:
            fetched = list(pool.map(_fetch, [e["ticker"] for e in top]))

        # Two cheap keyed reads instead of a query per row: the caches are small (one row
        # per top-N ticker) and this endpoint is hit on every app open. The LLM texts and
        # the 1y series are generated nightly (scripts/run_insights.py) — a warm local
        # call is ~5.6 s, which has no place in a request the phone waits on.
        insights = load_insights(db_path)
        series = load_price_series(db_path)

        return JSONResponse({
            "briefs": [
                build_brief(
                    e, f,
                    insight=insights.get(e["ticker"]),
                    chart=series.get(e["ticker"]),
                )
                for e, f in zip(top, fetched)
            ],
            "disclaimer": DISCLAIMER,
        })

    @app.get("/api/stack/{ticker}")
    def signal_stack(ticker: str) -> JSONResponse:
        # v6 P6: one ticker, every signal layer side by side — factor screen, entry composite,
        # ML score, external evidence, person track records. Absent layers are honest nulls,
        # never fabricated neutrals.
        if not re.fullmatch(r"[A-Za-z0-9.\-]{1,12}", ticker):
            return JSONResponse({"error": "Ungültiger Ticker."}, status_code=422)
        ticker = ticker.upper()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        screener = None
        run = load_latest_run(db_path)
        if run is not None:
            for bucket, picks in run.buckets.items():
                for pick in picks:
                    pick_dict = asdict(pick)
                    if pick_dict["instrument"]["ticker"] == ticker:
                        screener = {
                            "bucket": bucket,
                            "composite": pick_dict.get("composite"),
                            "factors": pick_dict.get("factors"),
                            "run_created_at": run.created_at,
                        }
                        break

        radar_entry = None
        watchlist = load_latest_watchlist(db_path)
        for entry in (watchlist or {}).get("entries", []):
            if entry["ticker"] == ticker:
                radar_entry = entry
                break

        events = events_in_window(db_path, window_days=30, now=now).get(ticker, [])
        return JSONResponse({
            "ticker": ticker,
            "screener": screener,
            "radar": radar_entry,
            "ml": latest_scores(db_path).get(ticker),
            "evidence_events": events,
            "person_scores": [
                s for s in load_person_scores(db_path)
                if any(
                    (e.get("details") or {}).get(k) == s["person"]
                    for e in events
                    for k in ("politician", "fund", "insider", "speaker")
                )
            ],
            "disclaimer": DISCLAIMER,
        })

    @app.get("/api/history")
    def history(limit: int = 20) -> JSONResponse:
        return JSONResponse({"runs": load_run_summaries(db_path, limit=limit)})

    @app.get("/api/portfolio")
    def portfolio() -> JSONResponse:
        pf = load_portfolio(db_path)
        if pf is None:
            return JSONResponse({"exists": False, "positions": [], "valuations": []})
        positions = []
        for ticker, pos in pf.positions.items():
            invested = pos.shares * pos.cost_basis
            last_price = pos.last_price if pos.last_price is not None else pos.cost_basis
            market_value = pos.shares * last_price
            pnl = market_value - invested
            positions.append({
                "ticker": ticker, "name": pos.instrument.name, "region": pos.instrument.region,
                "shares": pos.shares, "cost_basis": pos.cost_basis, "last_price": last_price,
                "invested": invested, "market_value": market_value,
                "pnl": pnl, "pnl_pct": (pnl / invested) if invested else 0.0,
                "opened_at": pos.opened_at,
            })
        return JSONResponse({
            "exists": True,
            "initial_capital": pf.initial_capital,
            "cash": pf.cash,
            "benchmark_ticker": pf.benchmark_ticker,
            "positions": positions,
            "valuations": load_valuations(db_path),
        })

    @app.get("/api/forward")
    def forward() -> JSONResponse:
        # No cache: reflects the forward paper accounts as the daily advance writes to the DB.
        accounts = load_all_accounts(forward_db)
        payload = []
        for acc in accounts:
            vals = load_forward_valuations(forward_db, acc.strategy_name)
            payload.append({
                "strategy_name": acc.strategy_name,
                "initial_capital": acc.initial_capital,
                "equity": acc.equity,
                "total_return": acc.equity / acc.initial_capital - 1.0,
                "benchmark_ticker": acc.benchmark_ticker,
                "benchmark_return": acc.benchmark_equity / acc.initial_capital - 1.0,
                "last_as_of": acc.last_as_of,
                "n_points": len(vals),
                "equity_curve": [[v["created_at"], v["equity"], v["benchmark_equity"]] for v in vals],
            })
        return JSONResponse({
            "available": len(accounts) > 0,
            "accounts": payload,
            "disclaimer": DISCLAIMER,
        })

    @app.get("/api/autodepot")
    def autodepot() -> JSONResponse:
        # No cache: reflects the auto-depot as the nightly advance writes to the DB (v10).
        account = load_autotrader_depot(autotrader_db)
        if account is None:
            return JSONResponse({"available": False, "disclaimer": DISCLAIMER})
        vals = load_autotrader_valuations(autotrader_db)
        latest = vals[-1] if vals else None
        return JSONResponse({
            "available": True,
            "account": {
                "initial_capital": account.initial_capital,
                "equity": account.equity,
                "total_return": account.equity / account.initial_capital - 1.0,
                "benchmark_ticker": account.benchmark_ticker,
                "benchmark_return": account.benchmark_equity / account.initial_capital - 1.0,
                "last_as_of": account.last_as_of,
                "weights": account.weights,
                "breaker_stage": account.breaker.stage,
                "breaker_changed_at": account.breaker.changed_at,
                "sleeve_mode": account.sleeve_mode,
                "pending_orders": (
                    None if account.pending_orders is None else {
                        "decided_as_of": account.pending_orders.decided_as_of,
                        "targets": account.pending_orders.targets,
                    }
                ),
            },
            # v13 O2: rebalances decided on one advance fill at the NEXT advance's open
            # (honest close fallback when no open exists — see each trade row's "fill")
            "fill_convention": "next-open (seit v13)",
            "latest": latest,  # exposure/drawdown/EUR of the newest valuation row
            "equity_curve": [
                [v["created_at"], v["equity"], v["benchmark_equity"]] for v in vals
            ],
            "sleeve_weights": load_latest_sleeve_weights(autotrader_db),
            "trades": load_autotrader_trades(autotrader_db, limit=50),
            "risk_events": load_autotrader_risk_events(autotrader_db, limit=20),
            "disclaimer": DISCLAIMER,
        })

    def _lane_last_prices(lane: str) -> dict[str, float]:
        """Last stored close per ticker for a lane, from the runner's OWN local snapshot.

        Read-only and offline: `refresh=False` reads the CSV the lane runner already wrote,
        so the phone's depot card costs no network call. Only the swing lane keeps such a
        snapshot — session trades intraday bars and crypto pulls Kraken, neither of which
        leaves a panel behind. Those lanes therefore report no live mark, and the card says
        so instead of showing a price it does not have.
        """
        if lane != "swing":
            return {}
        try:
            from equity_scout.data.etf_panel import load_snapshot

            closes = load_snapshot("data/prices/st_swing_panel.csv").closes
            return {
                str(col): float(closes[col].dropna().iloc[-1])
                for col in closes.columns
                if not closes[col].dropna().empty
            }
        except Exception:  # noqa: BLE001 - a missing snapshot is an honest absence
            return {}

    def _open_position(lane: str, ticker: str, pos) -> dict:  # noqa: ANN001
        """One open position plus what the card needs to judge it: where it stands now and
        the rules that will close it."""
        last = _lane_last_prices(lane).get(ticker)
        targets = position_targets(lane, entry_price=pos.entry_price)
        return {
            "ticker": ticker,
            "qty": pos.qty,
            "entry_price": pos.entry_price,
            "opened_at": pos.opened_at,
            "last_price": last,
            "unrealized_pct": (
                last / pos.entry_price - 1.0 if last and pos.entry_price > 0 else None
            ),
            **targets,
        }

    @app.get("/api/shortterm")
    def shortterm() -> JSONResponse:
        # No cache: reflects the arena lanes as their runners write to the DB (v11).
        from datetime import date as _date

        depot_account = load_autotrader_depot(autotrader_db)
        promoted_lanes = set(depot_account.promoted_lanes) if depot_account else set()
        lanes_payload = []
        for lane in LANES:
            book = load_st_book(shortterm_db, lane)
            if book is None:
                continue
            vals = load_st_valuations(shortterm_db, lane)
            trades = load_st_trades(shortterm_db, lane, limit=500)
            peak, max_dd = 0.0, 0.0
            for v in vals:
                peak = max(peak, v["equity"])
                if peak > 0:
                    max_dd = max(max_dd, 1.0 - v["equity"] / peak)
            latest = vals[-1] if vals else None
            lanes_payload.append({
                "lane": lane,
                "initial_capital": book.initial_capital,
                "equity": latest["equity"] if latest else book.cash,
                "total_return": latest["total_return"] if latest else 0.0,
                "benchmark_ticker": book.benchmark_ticker,
                "benchmark_return": latest["benchmark_return"] if latest else None,
                "max_drawdown": max_dd,
                # None for every lane that never routed a real order (swing, crypto).
                "execution_regime": get_st_lane_state(shortterm_db, lane, "execution_regime"),
                "open_positions": [
                    _open_position(lane, ticker, pos)
                    for ticker, pos in sorted(book.positions.items())
                ],
                "equity_curve": [[v["created_at"], v["equity"]] for v in vals],
                "stats": shortterm_stats(trades),
                "recent_trades": trades[:20],
                "promoted": lane in promoted_lanes,
                "promotion": _sanitise_promotion(lane_promotion_status(
                    load_st_trades(shortterm_db, lane, limit=5000), vals,
                    today=_date.today().isoformat(),
                )),
            })
        return JSONResponse({
            "available": len(lanes_payload) > 0,
            "lanes": lanes_payload,
            "disclaimer": DISCLAIMER,
        })

    def _sanitise_promotion(status: dict) -> dict:
        # float("inf") is not valid JSON — render-side gets None + a flag instead.
        pf = status.get("profit_factor")
        if pf is not None and pf == float("inf"):
            status = {**status, "profit_factor": None, "profit_factor_unbounded": True}
        return status

    @app.get("/api/overview")
    def overview() -> JSONResponse:
        """v12 I1: total wealth across all horizons in one payload — short (arena lanes),
        mid (ML sleeves) and long (rule sleeves) split of the Auto-Depot by its meta
        weights (an approximation, labelled as such). Books that do not exist are
        honestly absent; nothing is invented."""
        from datetime import date as _date

        today = _date.today().isoformat()
        books: list[dict] = []
        ml_share = None

        account = load_autotrader_depot(autotrader_db)
        vals = load_autotrader_valuations(autotrader_db)
        if account is not None and vals:
            last = vals[-1]
            prev = vals[-2] if len(vals) >= 2 else None
            books.append({
                "key": "autodepot", "label": "Auto-Depot", "horizon": "mid_long",
                "equity": last["equity"], "initial": account.initial_capital,
                "total_return": last["total_return"],
                "day_pnl": (last["equity"] - prev["equity"]) if prev else None,
                "as_of": last["created_at"],
            })
            weights_sum = sum(account.sleeve_weights.values())
            if weights_sum > 0:
                ml_share = sum(
                    w for n, w in account.sleeve_weights.items() if n in ML_SLEEVE_NAMES
                ) / weights_sum

        for lane in LANES:
            book = load_st_book(shortterm_db, lane)
            lane_vals = load_st_valuations(shortterm_db, lane)
            if book is None or not lane_vals:
                continue
            latest = lane_vals[-1]
            prior = [v for v in lane_vals if v["created_at"][:10] < today]
            baseline = prior[-1]["equity"] if prior else book.initial_capital
            books.append({
                "key": f"arena_{lane}", "label": f"Arena {LANE_LABELS.get(lane, lane)}",
                "horizon": "short",
                "equity": latest["equity"], "initial": book.initial_capital,
                "total_return": latest["total_return"],
                "day_pnl": latest["equity"] - baseline,
                "as_of": latest["created_at"],
            })

        if not books:
            return JSONResponse({"available": False, "disclaimer": DISCLAIMER})

        short_equity = sum(b["equity"] for b in books if b["horizon"] == "short")
        horizons: dict = {"short": {"equity": short_equity, "label": "Kurzfristig (Arena)"}}
        depot = next((b for b in books if b["key"] == "autodepot"), None)
        if depot is not None and ml_share is not None:
            note = "anteilig nach Sleeve-Gewichten (Näherung)"
            horizons["mid"] = {
                "equity": depot["equity"] * ml_share,
                "label": "Mittelfristig (ML-Bots im Auto-Depot)", "note": note,
            }
            horizons["long"] = {
                "equity": depot["equity"] * (1.0 - ml_share),
                "label": "Langfristig (Regel-Sleeves im Auto-Depot)", "note": note,
            }

        day_values = [b["day_pnl"] for b in books if b["day_pnl"] is not None]
        return JSONResponse({
            "available": True,
            "books": books,
            "horizons": horizons,
            "total": {
                "equity": sum(b["equity"] for b in books),
                "initial": sum(b["initial"] for b in books),
                "day_pnl": sum(day_values) if day_values else None,
            },
            "disclaimer": DISCLAIMER,
        })

    @app.get("/api/proof")
    def proof() -> JSONResponse:
        """v12 P2: honest report card per book — the "kann das funktionieren?"-view."""
        books = collect_proof_books(autotrader_db, shortterm_db, forward_db)
        return JSONResponse({
            "available": len(books) > 0,
            "books": books,
            "conviction": CONVICTION_THRESHOLDS,
            # The 60-day gate rides along so the frontend can render "Urteil ab Tag N"
            # progress without hardcoding a second copy of proof.MIN_DAYS_FOR_RATES.
            "min_judge_days": MIN_DAYS_FOR_RATES,
            "disclaimer": DISCLAIMER,
        })

    _TICKER_RE = re.compile(r"^[A-Za-z0-9.\-]{1,15}$")
    entry_cache: dict[str, dict] = {}  # key "TICKER:YYYY-MM-DD" -> payload; daily-fresh, no TTL timer

    @app.get("/api/entry/{ticker}")
    def entry(ticker: str) -> JSONResponse:
        from datetime import date

        import equity_scout.entry as entry_mod

        t = ticker.strip().upper()
        if not _TICKER_RE.match(t):
            return JSONResponse({"error": "Ungültiges Ticker-Symbol."}, status_code=400)
        cache_key = f"{t}:{date.today().isoformat()}"
        if cache_key in entry_cache:
            return JSONResponse(entry_cache[cache_key])
        try:
            closes, highs, lows = entry_mod.fetch_entry_history(t)
        except Exception:  # noqa: BLE001 - network hiccup -> honest gap, never a 500;
            # deliberately NOT cached so the next request may retry (v12 R11)
            return JSONResponse({
                "available": False, "ticker": t, "reason": "fetch_failed",
                "disclaimer": DISCLAIMER,
            })

        # A4: model-derived target/stop from the entry_tb champion's OWN vol-scaled barrier config
        # (never re-derived from hardcoded defaults). No champion / no persisted barrier_config /
        # too little price history for its vol_window -> an honest gap (None), never a guess.
        champ = entry_champion(db_path, family="entry_tb")
        barrier_config = champ[2].get("barrier_config") if champ is not None else None
        target_stop = entry_mod.compute_target_stop(closes, barrier_config) if barrier_config else None

        try:
            plan = entry_mod.compute_entry_plan(t, closes, highs, lows)
        except ValueError:
            # Too little valid price history (bad/illiquid ticker, or a thin yfinance response).
            payload = {
                "available": False, "ticker": t, "target_stop": target_stop,
                "disclaimer": DISCLAIMER,
            }
            entry_cache[cache_key] = payload
            return JSONResponse(payload)
        payload = {
            "available": True, "plan": asdict(plan), "target_stop": target_stop,
            "disclaimer": DISCLAIMER,
        }
        entry_cache[cache_key] = payload
        return JSONResponse(payload)

    def _chat_dossier_blocks(question: str) -> list[str]:
        """One dossier per stock the question mentions — the heart of "alles zu Aktien".

        Every fact comes from a local store the dashboard already serves; the only network
        touch is the 6 h-cached fundamentals lookup, and an unknown symbol gets at most ONE
        of those per question.
        """
        from equity_scout.chat_retrieval import candidate_symbols, find_tickers, stock_dossier
        from equity_scout.data.cache import load_cached_metrics
        from equity_scout.earnings_storage import earnings_within
        from equity_scout.fscore import load_f_score

        lexicon, lookup = _chat_lexicon(db_path)
        tickers = find_tickers(question, lexicon, lookup=lookup)[:_CHAT_MAX_DOSSIERS]
        unknown = [
            s for s in candidate_symbols(question, known=set(lexicon))
            if s not in tickers
        ][:1]
        tickers.extend(unknown)
        if not tickers:
            return []

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        today = now[:10]
        watchlist = load_latest_watchlist(db_path)
        by_ticker = {e["ticker"]: e for e in (watchlist or {}).get("entries", [])}
        insights = load_insights(db_path)
        all_pitches = load_pitches(db_path)
        metrics = load_cached_metrics(cache_db, tickers)
        events = events_in_window(
            db_path, window_days=_CHAT_EVIDENCE_WINDOW_DAYS, now=now, tickers=tickers,
        )
        earnings = {
            row["ticker"]: row["earnings_date"]
            for row in earnings_within(db_path, today=today, days=120)
        }
        run_id = latest_run_id(db_path)
        breakdowns = {
            row["ticker"]: row["breakdown"]
            for row in (load_run_scores(db_path, run_id) if run_id is not None else [])
        }

        blocks: list[str] = []
        for ticker in tickers:
            held: dict[str, float] = {}
            for lane in (LANE_NICO, LANE_AUTOPILOT):
                portfolio = load_lane_portfolio(db_path, lane)
                if portfolio is not None and ticker in portfolio.positions:
                    held[lane] = round(portfolio.positions[ticker].shares, 2)
            try:
                fundamentals = fetch_fundamentals_cached(ticker)
            except Exception:  # noqa: BLE001 - a failed lookup is an honest gap, not a 500
                fundamentals = None
            fetched_on, cached_metrics = metrics.get(ticker, (None, None))
            blocks.append(stock_dossier(
                ticker=ticker,
                name=lexicon.get(ticker),
                watchlist_entry=by_ticker.get(ticker),
                fundamentals=fundamentals,
                insight=insights.get(ticker),
                pitches=[p for p in all_pitches if p["ticker"] == ticker],
                evidence_events=events.get(ticker, []),
                held_by=held,
                metrics=cached_metrics,
                metrics_fetched_on=fetched_on,
                factor_breakdown=breakdowns.get(ticker),
                fscore=load_f_score(db_path, ticker),
                next_earnings=earnings.get(ticker),
            ))
            people = events.get(ticker, [])
            if people:
                from equity_scout.chat_retrieval import people_lines
                blocks.append(
                    f"WER HANDELT/SPRICHT ÜBER {ticker} (letzte "
                    f"{_CHAT_EVIDENCE_WINDOW_DAYS} Tage):\n"
                    + "\n".join(people_lines(people))
                )
        return blocks

    def _chat_strategies_block() -> str:
        """The pre-2026-08-07 chat context: strategies, ML, research, forward, screener."""
        from equity_scout.chat import build_dashboard_context

        reports = get_reports() or []
        strategies = [asdict(r) for r in reports]
        ml = asdict(reports_cache["ml"]) if "ml" in reports_cache else None  # only if already trained
        research = research_summary(ledger)
        forward = [
            {
                "strategy_name": a.strategy_name,
                "total_return": a.equity / a.initial_capital - 1.0,
                "benchmark_return": a.benchmark_equity / a.initial_capital - 1.0,
                "n_points": len(load_forward_valuations(forward_db, a.strategy_name)),
            }
            for a in load_all_accounts(forward_db)
        ]
        run = load_latest_run(db_path)
        bucket_labels = {"defensive": "Defensiv", "balanced": "Ausgewogen", "aggressive": "Aggressiv"}
        screener = (
            {
                bucket_labels.get(b, b): [
                    {
                        "ticker": p.instrument.ticker,
                        "name": p.instrument.name,
                        "region": p.instrument.region,
                        "composite": round(p.composite * 100),
                    }
                    for p in picks[:5]
                ]
                for b, picks in run.buckets.items()
            }
            if run is not None and run.buckets
            else None
        )
        return build_dashboard_context(
            strategies=strategies, ml=ml, research=research, forward=forward, screener=screener
        )

    def _chat_context(question: str) -> str:
        """Glossary + the blocks this question actually needs + a dossier per mentioned
        stock. Routing keeps the prompt short: the measurement showed a 7B model losing
        the thread when handed the whole dashboard for a single-stock question."""
        from equity_scout.chat import GLOSSARY
        from equity_scout.chat_retrieval import route_topics

        topics = route_topics(question)
        blocks: list[str] = [GLOSSARY]
        blocks.extend(_chat_dossier_blocks(question))
        overview = "ueberblick" in topics
        if "depots" in topics or overview:
            blocks.append(_chat_depots_block(db_path, autotrader_db, shortterm_db))
        if "ergebnisse" in topics:
            blocks.append(_chat_proof_block(autotrader_db, shortterm_db, forward_db))
        if "personen" in topics:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            blocks.append(_chat_people_block(db_path, now))
        if "markt" in topics or overview:
            blocks.append(_chat_regime_block(reports_cache.get("regime")))
        if "inbox" in topics or overview:
            blocks.append(_chat_inbox_block(load_pitches(db_path)))
        if "strategien" in topics or overview:
            blocks.append(_chat_strategies_block())
        return "\n\n".join(b for b in blocks if b)

    @app.post("/api/chat")
    def chat(body: dict) -> JSONResponse:
        import equity_scout.chat as chat_mod
        from equity_scout.chat import REFUSAL_ANSWER, ChatError
        from equity_scout.chat_retrieval import is_advice_question

        question = str((body or {}).get("question", "")).strip()
        if not question:
            return JSONResponse({"error": "Keine Frage übergeben."}, status_code=400)
        if is_advice_question(question):
            # Fixed sentence, zero LLM involvement — the refusal must be unconditional.
            return JSONResponse({"answer": REFUSAL_ANSWER, "disclaimer": DISCLAIMER})
        try:
            answer = chat_mod.ask_ollama(question, _chat_context(question))
        except ChatError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse({"answer": answer, "disclaimer": DISCLAIMER})

    @app.post("/api/chat/stream")
    def chat_stream(body: dict):  # noqa: ANN202 - StreamingResponse | JSONResponse
        import equity_scout.chat as chat_mod
        from fastapi.responses import StreamingResponse

        from equity_scout.chat import REFUSAL_ANSWER
        from equity_scout.chat_retrieval import is_advice_question

        question = str((body or {}).get("question", "")).strip()
        if not question:
            return JSONResponse({"error": "Keine Frage übergeben."}, status_code=400)
        if is_advice_question(question):
            return StreamingResponse(iter([REFUSAL_ANSWER]), media_type="text/plain")
        context = _chat_context(question)

        def _gen():  # noqa: ANN202
            try:
                yield from chat_mod.stream_ollama(question, context)
            except chat_mod.ChatError as exc:
                # Mid-stream the status code is already sent, so errors travel in-band —
                # the panel shows whatever arrived plus this line, never a silent stop.
                yield f"\n[Fehler: {exc}]"

        return StreamingResponse(_gen(), media_type="text/plain")

    @app.get("/api/health")
    def health() -> JSONResponse:
        # Liveness only: the phone cockpit polls this every 30 s to tell live data from
        # service-worker cache. Touches no DB and no feed on purpose — polling a data
        # endpoint (e.g. /api/regime, which fetches SPY/VIX/yields through yfinance)
        # would mean rate-limited requests twice a minute for a reachability check.
        # The DASH_TOKEN middleware still guards it, which is wanted: an unauthenticated
        # probe must not report the cockpit as reachable.
        return JSONResponse({"ok": True})

    @app.get("/api/logo/{ticker}")
    def logo(ticker: str) -> Response:
        # Plain `def` (not `async def`): FastAPI runs sync route handlers in a threadpool,
        # so the one live network call ensure_logo may make on a cache miss (10 s timeout,
        # see logos.py) never blocks the event loop - same convention as /api/entry/{ticker}.
        if not re.fullmatch(r"[A-Za-z0-9.\-]{1,15}", ticker):
            return JSONResponse({"error": "Ungültiger Ticker."}, status_code=422)
        path = ensure_logo(ticker)
        if path is None:
            # A missing logo is a NORMAL answer, not an error: the frontend falls back to a
            # monogram badge. 404 (not 200 + null) so the service worker/browser cache never
            # confuses "no logo" with a cacheable image response.
            return JSONResponse({"error": "Kein Logo verfügbar."}, status_code=404)
        # The bytes we serve here never change once cached (ensure_logo never re-fetches a
        # hit), so a long max-age is safe. 30 days rather than "forever": the only way to
        # correct a bad cached image today is deleting the file on disk, and we don't want a
        # phone holding onto a stale/wrong image for a year after that.
        return Response(
            content=path.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=2592000"},
        )

    @app.get("/api/inbox")
    def inbox() -> JSONResponse:
        # Each pitch carries its PITCH-TIME price/zone; the decision needs TODAY's picture
        # (Nico 2026-08-06: "ist grad guter Einstiegspreis oder nicht? Was wäre Potenzial?").
        # Context comes from the current watchlist + the cached fundamentals — same sources
        # and the same bounded pool as /api/briefs, and only for OPEN pitches (decided rows
        # need no buying context, and fetching for up to 100 of them would be a fetch storm).
        pitches = load_pitches(db_path)
        watchlist = load_latest_watchlist(db_path)
        by_ticker = {e["ticker"]: e for e in (watchlist or {}).get("entries", [])}
        open_tickers = sorted(
            {p["ticker"] for p in pitches if p["status"] == "open" and p["ticker"] in by_ticker}
        )

        def _fundamentals(ticker: str):
            try:
                return fetch_fundamentals_cached(ticker)
            except Exception:  # noqa: BLE001 - one bad ticker must never break the inbox
                return None

        with ThreadPoolExecutor(max_workers=5) as pool:
            fundamentals = dict(zip(open_tickers, pool.map(_fundamentals, open_tickers)))

        # Company names also for off-watchlist tickers (run_scores fallback) — a bare
        # "9064.T" identifies nothing; None when truly unknown, never an invented name.
        names = _known_company_names(db_path)
        enriched = []
        for p in pitches:
            entry = by_ticker.get(p["ticker"]) if p["status"] == "open" else None
            context = pitch_market_context(entry, fundamentals.get(p["ticker"]))
            if context["name"] is None:
                context["name"] = names.get(p["ticker"])
            enriched.append({**p, **context})
        return JSONResponse({"pitches": enriched, "disclaimer": DISCLAIMER})

    @app.get("/api/evidence")
    def evidence() -> JSONResponse:
        # Edge monitor: recent raw events (30d), the alerts that fired, the MEASURED
        # per-source hit-rates from the predict-then-resolve ledger, the measured
        # person track records (gated entries carry scoreable=False, never a number),
        # and the honest event-reaction study (Strang B4: is our latency worth
        # anything on beat/miss/guidance events — 1h always marked not measurable).
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # "V — 2 Kongressmitglieder haben gekauft" is unreadable without the company; the
        # alert rows carry only a ticker, so the name is joined on here (null when unknown).
        names = _known_company_names(db_path)
        alerts = [
            {**alert, "name": names.get(alert["ticker"])}
            for alert in load_alerts(db_path, limit=20)
        ]
        return JSONResponse(
            {
                "events_by_ticker": events_in_window(db_path, window_days=30, now=now),
                "recent_alerts": alerts,
                "stats_by_source": stats_by_source(db_path),
                "person_scores": load_person_scores(db_path),
                "event_reactions": aggregate_reactions(db_path),
                # {ticker: company name} so the people/voices views can say "Visa"
                # instead of "V" — same known-names source as the alerts above.
                "names": names,
                "disclaimer": DISCLAIMER,
            }
        )

    @app.post("/api/inbox/{pitch_id}/decision")
    def inbox_decision(pitch_id: int, body: dict) -> JSONResponse:
        # Mirrors POST /api/chat's idiom: plain dict body + manual validation, and the
        # file-wide {"error": ...} shape for every error status. Action validity and
        # pitch-state conflicts are distinct error paths, checked in this order.
        action = str((body or {}).get("action", ""))
        if action not in ACTIONS:
            return JSONResponse({"error": "Ungültige Aktion."}, status_code=422)
        decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not decide_pitch(db_path, pitch_id, action, decided_at=decided_at):
            return JSONResponse(
                {"error": "Pitch unbekannt oder bereits entschieden."}, status_code=409
            )
        # Return the updated row so the dashboard can update in place without a refetch.
        return JSONResponse(
            {"ok": True, "pitch": get_pitch(db_path, pitch_id), "disclaimer": DISCLAIMER}
        )

    @app.get("/api/arena")
    def arena() -> JSONResponse:
        # No cache: reflects the two lanes as scripts/run_lanes.py advances them in the DB.
        lanes: list[dict] = []
        for lane in (LANE_NICO, LANE_AUTOPILOT):
            pf = load_lane_portfolio(db_path, lane)
            if pf is None:
                continue
            valuations = load_lane_valuations(db_path, lane)  # oldest -> newest
            latest = valuations[-1] if valuations else None
            lanes.append({
                "lane": lane,
                "initial_capital": pf.initial_capital,
                "total_value": latest["total_value"] if latest else pf.cash,
                "total_return": latest["total_return"] if latest else 0.0,
                "benchmark_return": latest["benchmark_return"] if latest else 0.0,
                "open_positions": [
                    {
                        "ticker": ticker,
                        "name": pos.instrument.name,
                        "shares": pos.shares,
                        "cost_basis": pos.cost_basis,
                        "last_price": pos.last_price if pos.last_price is not None else pos.cost_basis,
                        "opened_at": pos.opened_at,
                    }
                    for ticker, pos in pf.positions.items()
                ],
                "equity_curve": [
                    [v["valued_on"], v["total_value"], v["benchmark_value"]] for v in valuations
                ],
                "trades": load_lane_trades(db_path, lane, limit=50),
            })
        return JSONResponse({
            "available": len(lanes) > 0,
            "lanes": lanes,
            "disclaimer": DISCLAIMER,
        })

    @app.get("/api/model")
    def model() -> JSONResponse:
        # No cache: reflects the entry-model registry + prediction ledger as the train/resolve CLIs
        # write to the DB. Champion metadata is read from the summary (no artifact unpickle on the
        # read path). The score RANKS entry attractiveness out-of-sample — not a forecast, not advice.
        summary = registry_summary(db_path)
        versions = summary["versions"]
        champion_version = summary["champion_version"]
        champ = None
        if champion_version is not None:
            row = next(v for v in versions if v["version"] == champion_version)
            champ = {
                "version": row["version"],
                "created_at": row["created_at"],
                "model_kind": row["model_kind"],
                "metrics": row["metrics"],
            }
        # Live drift: champion's training feature means (registered since v6) vs the means of
        # recent live predictions. None stays None when either side is missing — never fabricated.
        drift = None
        if champ is not None:
            train_means = champ["metrics"].get("feature_means")
            recent = recent_prediction_features(db_path)
            if train_means and recent:
                drift = drift_snapshot(train_means, recent)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return JSONResponse({
            "available": bool(versions),
            "champion": champ,
            "registry": versions,
            "resolved": resolved_stats(db_path),
            "resolved_windows": [
                resolved_stats_windowed(db_path, window_days=window, now=now)
                for window in (30, 90)
            ],
            "drift": drift,
            # Pipeline caveats (plan v7 strand C, task C4): structural, not per-model — see
            # constants.MODEL_CAVEATS for what each one documents and where.
            "caveats": MODEL_CAVEATS,
            "disclaimer": DISCLAIMER,
        })

    @app.get("/api/model/history")
    def model_history() -> JSONResponse:
        # The learning-curve data source (plan v6 P4): per family every registered version's OOS
        # quality in training order, plus the champion promotion timeline. The curve shows what IS
        # — including deterioration; nothing is smoothed away and each point carries its n.
        summary = registry_summary(db_path)
        families: dict[str, list[dict]] = {}
        for row in sorted(summary["versions"], key=lambda v: v["version"]):
            metrics = row["metrics"]
            families.setdefault(row["family"], []).append({
                "version": row["version"],
                "created_at": row["created_at"],
                "model_kind": row["model_kind"],
                "is_champion": row["is_champion"],
                "auc": metrics.get("auc"),
                "brier": metrics.get("brier"),
                "rank_ic": metrics.get("rank_ic"),
                "n_oos": metrics.get("n_oos"),
                "calibrated": metrics.get("calibrated"),
                "horizon_days": metrics.get("horizon_days"),
            })
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return JSONResponse({
            "available": bool(families),
            "families": families,
            "promotions": load_champion_history(db_path),
            "resolved_windows": [
                resolved_stats_windowed(db_path, window_days=window, now=now)
                for window in (30, 90)
            ],
            # Daily learning curve (plan v7 strand C, task C1): one point per calendar day
            # (scripts/run_learning_snapshot.py, chained after the nightly retrain), so daily
            # training is visible even on nights the champion does not flip. Empty until the
            # first snapshot has run — never backfilled.
            "daily_curve": load_daily_curve(db_path),
            # Same structural pipeline caveats as /api/model (plan v7 strand C, task C4) — the
            # learning-curve view is exactly where "the model gets better day by day" is
            # suggested, so it must carry the same honesty caveats, not just the generic
            # disclaimer. Reuses constants.MODEL_CAVEATS, never a separate copy.
            "caveats": MODEL_CAVEATS,
            "disclaimer": DISCLAIMER,
        })

    # Serve the built React dashboard. Mounted at "/" LAST so the /api/* routes above win.
    # Run `cd frontend && npm install && npm run build` to produce dist/.
    if _DIST.exists():
        app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
    else:
        @app.get("/")
        def index() -> PlainTextResponse:
            return PlainTextResponse(
                "Dashboard not built. Run: cd frontend && npm install && npm run build"
            )

    return app
