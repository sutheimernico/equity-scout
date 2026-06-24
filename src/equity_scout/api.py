"""Read-only API for the dashboard. Serves the latest run snapshot + disclaimer."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from equity_scout.constants import DEFAULT_DB_PATH, DISCLAIMER
from equity_scout.storage import load_latest_run

_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


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
            "buckets": {b: [asdict(p) for p in picks] for b, picks in run.buckets.items()},
            "disclaimer": DISCLAIMER,
        }
        return JSONResponse(payload)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_FRONTEND)

    return app
