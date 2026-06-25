"""Read-only API for the dashboard. Serves the latest run snapshot + strategy reports + disclaimer."""
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from equity_scout.buckets import BUCKET_WEIGHTS
from equity_scout.constants import DEFAULT_DB_PATH, DEFAULT_FORWARD_DB_PATH, DISCLAIMER
from equity_scout.data.etf_panel import DEFAULT_SNAPSHOT, load_snapshot
from equity_scout.forward_storage import load_all_accounts
from equity_scout.forward_storage import load_valuations as load_forward_valuations
from equity_scout.portfolio_storage import load_portfolio, load_valuations
from equity_scout.storage import load_latest_run, load_run_summaries
from equity_scout.ml.ledger import DEFAULT_LEDGER_PATH
from equity_scout.ml.research_view import research_summary
from equity_scout.strategy_service import BENCHMARK_NAME, build_ml_report, build_reports

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(
    db_path: str = DEFAULT_DB_PATH,
    snapshot: str = DEFAULT_SNAPSHOT,
    ledger: str = DEFAULT_LEDGER_PATH,
    forward_db: str = DEFAULT_FORWARD_DB_PATH,
) -> FastAPI:
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

            reports_cache["ml"] = build_ml_report(_load(snapshot))
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
            "buckets": {b: [asdict(p) for p in picks] for b, picks in run.buckets.items()},
            "bucket_weights": BUCKET_WEIGHTS,
            "disclaimer": DISCLAIMER,
        }
        return JSONResponse(payload)

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
        context = build_dashboard_context(strategies=strategies, ml=ml, research=research, forward=forward)
        try:
            answer = ask_ollama(question, context)
        except ChatError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse({"answer": answer})

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
