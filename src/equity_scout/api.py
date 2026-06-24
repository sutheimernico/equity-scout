"""Read-only API for the dashboard. Serves the latest run snapshot + disclaimer."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from equity_scout.buckets import BUCKET_WEIGHTS
from equity_scout.constants import DEFAULT_DB_PATH, DISCLAIMER
from equity_scout.storage import load_latest_run, load_run_summaries

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(db_path: str = DEFAULT_DB_PATH) -> FastAPI:
    app = FastAPI(title="equity-scout")

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
