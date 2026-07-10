"""API for the dashboard. Serves the latest run snapshot + strategy reports + disclaimer,
plus the decision inbox (GET listing, POST one-tap buy/pass/later decisions)."""
from __future__ import annotations

import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from equity_scout.buckets import BUCKET_WEIGHTS
from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_FORWARD_DB_PATH, DISCLAIMER
from equity_scout.data.etf_panel import DEFAULT_SNAPSHOT, load_snapshot
from equity_scout.evidence.ledger import stats_by_source
from equity_scout.evidence.storage import events_in_window, load_alerts
from equity_scout.forward_storage import load_all_accounts
from equity_scout.forward_storage import load_valuations as load_forward_valuations
from equity_scout.inbox_storage import decide_pitch, get_pitch, load_pitches
from equity_scout.lane_storage import (
    load_lane_portfolio,
    load_lane_trades,
    load_lane_valuations,
)
from equity_scout.lanes import LANE_AUTOPILOT, LANE_NICO
from equity_scout.portfolio_storage import load_portfolio, load_valuations
from equity_scout.radar_storage import load_latest_watchlist
from equity_scout.storage import init_db, load_latest_run, load_run_summaries
from equity_scout.telegram_client import ACTIONS
from equity_scout.ml.ledger import DEFAULT_LEDGER_PATH, champion
from equity_scout.ml.model_registry import registry_summary
from equity_scout.ml.prediction_ledger import resolved_stats
from equity_scout.ml.research_view import research_summary
from equity_scout.strategy_service import BENCHMARK_NAME, build_ml_report, build_reports

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(
    db_path: str = DEFAULT_DB_PATH,
    snapshot: str = DEFAULT_SNAPSHOT,
    ledger: str = DEFAULT_LEDGER_PATH,
    forward_db: str = DEFAULT_FORWARD_DB_PATH,
) -> FastAPI:
    # The read API may face a DB written before a schema migration (e.g. the
    # data_quality column); init_db is idempotent and carries the migrations.
    init_db(db_path)
    app = FastAPI(title="equity-scout")
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

    @app.get("/api/latest")
    def latest() -> JSONResponse:
        run = load_latest_run(db_path)
        if run is None:
            return JSONResponse({"buckets": {}, "gated_out": {}, "disclaimer": DISCLAIMER})
        payload = {
            "created_at": run.created_at,
            "universe_size": run.universe_size,
            "gated_out": run.gated_out,
            "gate_stats": run.gate_stats,
            "data_quality": run.data_quality,
            "buckets": {b: [asdict(p) for p in picks] for b, picks in run.buckets.items()},
            "bucket_weights": BUCKET_WEIGHTS,
            "disclaimer": DISCLAIMER,
        }
        return JSONResponse(payload)

    @app.get("/api/radar")
    def radar() -> JSONResponse:
        watchlist = load_latest_watchlist(db_path)
        return JSONResponse({"watchlist": watchlist, "disclaimer": DISCLAIMER})

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
        closes, highs, lows = entry_mod.fetch_entry_history(t)
        try:
            plan = entry_mod.compute_entry_plan(t, closes, highs, lows)
        except ValueError:
            # Too little valid price history (bad/illiquid ticker, or a thin yfinance response).
            payload = {"available": False, "ticker": t, "disclaimer": DISCLAIMER}
            entry_cache[cache_key] = payload
            return JSONResponse(payload)
        payload = {"available": True, "plan": asdict(plan), "disclaimer": DISCLAIMER}
        entry_cache[cache_key] = payload
        return JSONResponse(payload)

    @app.post("/api/chat")
    def chat(body: dict) -> JSONResponse:
        from equity_scout.chat import ChatError, ask_ollama, build_dashboard_context

        question = str((body or {}).get("question", "")).strip()
        if not question:
            return JSONResponse({"error": "Keine Frage übergeben."}, status_code=400)

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
        context = build_dashboard_context(
            strategies=strategies, ml=ml, research=research, forward=forward, screener=screener
        )
        try:
            answer = ask_ollama(question, context)
        except ChatError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse({"answer": answer})

    @app.get("/api/inbox")
    def inbox() -> JSONResponse:
        return JSONResponse({"pitches": load_pitches(db_path), "disclaimer": DISCLAIMER})

    @app.get("/api/evidence")
    def evidence() -> JSONResponse:
        # Edge monitor: recent raw events (30d), the alerts that fired, and the
        # MEASURED per-source hit-rates from the predict-then-resolve ledger.
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return JSONResponse(
            {
                "events_by_ticker": events_in_window(db_path, window_days=30, now=now),
                "recent_alerts": load_alerts(db_path, limit=20),
                "stats_by_source": stats_by_source(db_path),
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
        return JSONResponse({
            "available": bool(versions),
            "champion": champ,
            "registry": versions,
            "resolved": resolved_stats(db_path),
            "drift": None,  # v1: surfaced as None; a live drift snapshot is a later enhancement
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
