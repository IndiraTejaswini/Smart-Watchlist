"""FastAPI application — docs/BUILD_SPEC.md §4.1, §16.

Deliberately thin. BUILD_PLAN task 9.1 owns the real app factory — settings,
DB session lifecycle, RFC 7807 error handling — and 9.7 mounts the built SPA.
This exists now only because task 1.4's acceptance names an endpoint
(`/api/eval/unparsed-actions`), and an endpoint needs an app to hang from.

Kept to routing and nothing else so that Phase 9 extends it rather than
unpicking it.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from redis import Redis

from app.api import brief_explain, core, quotes, watchlist, ws
from app.api import eval as eval_api
from app.config import Settings, assert_production_ready, get_settings
from app.db import get_engine
from app.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.ingest.calendar import load_trading_calendar
from app.ingest.index_snapshot import estimated_from_open_count
from app.ingest.nse_client import nse_breaker_state
from app.ingest.polling import latest_escalated_dates
from app.timeutil import IST, SessionPhase, session_phase


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Refuse a misconfigured production boot rather than serving a blank page
    # or an empty Brief to a reviewer. No-op outside ENV=production.
    assert_production_ready(settings)
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
    def health(response: Response) -> dict[str, object]:
        """Per-dependency status plus `last_bhavcopy_date` — §19.2.

        `last_bhavcopy_date` is the field that distinguishes a healthy deploy
        from one that came up against an empty database, which is the failure
        this endpoint exists to catch. Redis is probed rather than assumed:
        reporting a dependency as up without asking it is worse than not
        reporting it at all.
        """
        estimated_count = 0
        last_bhavcopy = None
        try:
            with get_engine().connect() as conn:
                estimated_count = estimated_from_open_count(conn)
                last_bhavcopy = conn.execute(
                    sa.text("SELECT max(date) FROM daily_bars")
                ).scalar()
            db_ok = True
        except Exception:
            db_ok = False

        # Redis holds quotes and caches, all of which are rebuildable from
        # Postgres (§3.1). Losing it degrades the app; it does not stop it,
        # so it is reported but does not decide the status code.
        try:
            Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2).ping()
            redis_ok = True
        except Exception:
            redis_ok = False

        if db_ok:
            status = "ok" if redis_ok else "degraded"
        else:
            status = "unhealthy"
            response.status_code = 503

        return {
            "status": status,
            "db": db_ok,
            "redis": redis_ok,
            "last_bhavcopy_date": str(last_bhavcopy) if last_bhavcopy else None,
            "estimated_from_open_count": estimated_count,
            "nse_breaker_state": nse_breaker_state(),
        }

    @app.get("/api/market/status")
    def market_status() -> dict[str, object]:
        """§16 `MarketStatusResponse`.

        Reports the *session* the market is in and how far the ingested data
        reaches, because that is what the client renders. The operational
        escalation state is folded into `banner` rather than into `session`:
        a late bhavcopy is a data-quality fact, not a change of session, and
        conflating the two is what made an earlier revision of this endpoint
        unreadable to the client's §16 schema.
        """
        now = datetime.now(IST)
        with get_engine().connect() as conn:
            dates = latest_escalated_dates(conn)
            last_bhavcopy = conn.execute(
                sa.text("SELECT max(date) FROM daily_bars")
            ).scalar()
            delivery_through = conn.execute(
                sa.text("SELECT max(date) FROM delivery_stats")
            ).scalar()
            try:
                # session_phase only reads today's row, so today is the
                # whole range this needs — no window constant to invent (R1).
                calendar = load_trading_calendar(conn, now.date(), now.date())
            except Exception:
                calendar = None

        # A window the exchange has not published is not a phase we may guess
        # at (§5.2) — CLOSED is the honest answer, not an assumed 09:15.
        session = SessionPhase.CLOSED.value
        if calendar is not None:
            try:
                session = session_phase(now, calendar).value
            except Exception:
                session = SessionPhase.CLOSED.value

        # This build ingests end-of-day exchange files and has no live broker
        # feed attached, so there is no state in which it can honestly claim
        # LIVE. Outside a session that is CLOSED; inside one it is NO_DATA.
        feed_state = "CLOSED" if session == SessionPhase.CLOSED.value else "NO_DATA"

        return {
            # Two audiences, two fields, deliberately not merged: `status` is
            # the ingest/ops health an operator pages on, `session` is the
            # market phase the client renders. An earlier revision had only
            # the first and called it "status", which the client's §16 schema
            # could not read at all.
            "status": "ESCALATED" if dates else "OK",
            "as_of": now.isoformat(),
            "session": session,
            "feed_state": feed_state,
            "banner": (
                f"Bhavcopy missing; dependent jobs paused. Escalated dates: "
                f"{', '.join(str(day) for day in dates)}"
                if dates
                else None
            ),
            "data_quality": {
                "last_bhavcopy_date": str(last_bhavcopy) if last_bhavcopy else None,
                "delivery_final_through": (
                    str(delivery_through) if delivery_through else None
                ),
                "symbols_below_liquidity_floor": [],
                "degraded_baselines": [],
                "index_0930_source": None,
            },
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
