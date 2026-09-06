"""FastAPI application — ARCHITECTURE.md §4.1, §16.

Deliberately thin. BUILD_PLAN task 9.1 owns the real app factory — settings,
DB session lifecycle, RFC 7807 error handling — and 9.7 mounts the built SPA.
This exists now only because task 1.4's acceptance names an endpoint
(`/api/eval/unparsed-actions`), and an endpoint needs an app to hang from.

Kept to routing and nothing else so that Phase 9 extends it rather than
unpicking it.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import brief_explain, core, quotes, watchlist, ws
from app.api import eval as eval_api
from app.config import Settings, get_settings
from app.db import get_engine
from app.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.ingest.index_snapshot import estimated_from_open_count
from app.ingest.nse_client import nse_breaker_state
from app.ingest.polling import latest_escalated_dates


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="The Brief — an attention allocator with a budget.",
        version="0.1.0",
    )
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(eval_api.router)
    app.include_router(brief_explain.router)
    app.include_router(watchlist.router)
    app.include_router(core.router)
    app.include_router(quotes.router)
    app.include_router(ws.router)

    @app.get("/api/health")
    def health() -> dict[str, object]:
        try:
            with get_engine().connect() as conn:
                estimated_from_open_count(conn)
            db_ok = True
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "db": db_ok, "redis": True}

    @app.get("/api/market/status")
    def market_status() -> dict[str, object]:
        with get_engine().connect() as conn:
            dates = latest_escalated_dates(conn)
        return {
            "status": "ESCALATED" if dates else "OK",
            "banner": (
                f"Bhavcopy missing; dependent jobs paused. Escalated dates: "
                f"{', '.join(str(day) for day in dates)}"
                if dates
                else None
            ),
            "escalated_dates": [str(day) for day in dates],
            "nse_breaker_state": nse_breaker_state(),
        }

    dist = Path(settings.STATIC_DIST_PATH)
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str, request: Request):
        if full_path == "api" or full_path.startswith("api/") or full_path in {
            "docs",
            "openapi.json",
        }:
            raise HTTPException(status_code=404, detail="Not Found")
        requested = dist / full_path
        if requested.is_file():
            return FileResponse(requested)
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index, media_type="text/html")
        raise HTTPException(status_code=404, detail="Not Found")

    return app


app = create_app()
