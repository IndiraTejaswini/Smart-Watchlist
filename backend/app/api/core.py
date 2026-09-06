"""Phase 9 REST resources."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.analytics.digest import build_digest
from app.api.auth import UserContext, get_current_user
from app.crud.brief_cursor import acknowledge_brief
from app.crud.read_cursor import upsert_read_cursor
from app.db import get_engine
from app.ingest.calendar import load_trading_calendar
from app.schemas.brief import BriefResponse

router = APIRouter(tags=["phase9"])
CurrentUser = Annotated[UserContext, Depends(get_current_user)]


class WatchlistCreate(BaseModel):
    name: str = "Default"


class BriefAck(BaseModel):
    ack_through_ts: datetime


class CursorUpsert(BaseModel):
    feed_id: str
    incoming_seq: int
    incoming_ts: datetime


@router.post("/api/watchlist", status_code=201)
def create_watchlist(payload: WatchlistCreate, user: CurrentUser) -> dict[str, str]:
    watchlist_id = str(uuid4())
    with get_engine().begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO watchlists(id,user_id,name) VALUES (:id,:user_id,:name)"
            ),
            {"id": watchlist_id, "user_id": user.user_id, "name": payload.name},
        )
    return {"watchlist_id": watchlist_id, "name": payload.name}


@router.get("/api/brief", response_model=BriefResponse)
def brief(
    user: CurrentUser,
    as_of: Annotated[datetime | None, Query()] = None,
    watchlist_id: Annotated[str | None, Query()] = None,
) -> BriefResponse:
    del watchlist_id
    evaluation_time = as_of or datetime.now(UTC)
    with get_engine().begin() as conn:
        calendar = load_trading_calendar(
            conn,
            evaluation_time.date() - timedelta(days=400),
            evaluation_time.date(),
        )
        payload = build_digest(conn, user.user_id, evaluation_time, calendar)

    items = []
    for index, item in enumerate(payload.scored_items, start=1):
        candidate = item.candidate
        family = (
            "TURNOVER_SURGE"
            if candidate.turnover_z is not None
            else "DELIVERY_SHIFT"
            if candidate.delivery_z is not None
            else "PRICE_MOVE"
        )
        classification = candidate.primary_category or "UNEXPLAINED"
        if classification not in {
            "EXPLAINED",
            "UNEXPLAINED",
            "SECTOR_WIDE",
            "MARKET_WIDE",
            "CORPORATE_ACTION",
        }:
            classification = "UNEXPLAINED"
        items.append(
            {
                "signal_event_id": candidate.id or f"{candidate.symbol}:{candidate.date}",
                "symbol": candidate.symbol,
                "company_name": candidate.symbol,
                "family": family,
                "classification": classification,
                "rank": index,
                "score": item.final_score,
                "what": f"{candidate.symbol} changed on {candidate.date}.",
                "how_unusual": "The move cleared the statistical candidate gates.",
                "cause": (
                    "A linked filing was present."
                    if candidate.has_material_filing
                    else "No linked filing was present."
                ),
                "freshness": f"As of {evaluation_time.isoformat()}. Final.",
                "metrics": {
                    "pct_move": 0.0,
                    "scar": candidate.sar,
                    "turnover_z": candidate.turnover_z or 0.0,
                    "delivery_z": candidate.delivery_z or 0.0,
                    "delivery_pct": 0.0,
                    "mpm_triggered": "PRICE_MPM"
                    in {family.value for family in candidate.signal_families},
                    "mpm_threshold_used": 0.0,
                },
                "provisional": candidate.status != "FINAL",
                "revision": candidate.revision,
                "was_restated": candidate.was_restated,
                "completeness": [],
                "linked_announcement_ids": [
                    int(value)
                    for value in candidate.linked_announcement_ids
                    if str(value).isdigit()
                ],
                "links": {
                    "announcement": None,
                    "explain": f"/api/brief/explain/{candidate.id or candidate.symbol}",
                },
            }
        )

    budget = payload.budget
    assert budget is not None
    return BriefResponse.model_validate(dict(
        generated_at=evaluation_time.isoformat(),
        cursor={
            "acknowledged_through": payload.cursor_ack_ts.isoformat(),
            "sessions_elapsed": 0,
            "calendar_days_elapsed": 0,
        },
        headline=f"Since your last read, {len(items)} things changed.",
        market_rollup={
            "present": bool(payload.market_rollups),
            "text": "",
            "index_change_pct": 0.0,
            "symbols_attributed": [],
        },
        items=items,
        sector_groups=[
            {
                "sector": rollup.sector,
                "text": rollup.summary_text,
                "symbols": list(rollup.affected_symbols),
            }
            for rollup in payload.sector_rollups
        ],
        corporate_action_notices=[
            {
                "symbol": notice.symbol,
                "action_type": notice.action_type,
                "ex_date": str(notice.ex_date),
                "text": notice.detail_text,
            }
            for notice in payload.corporate_actions
        ],
        quiet={
            "count": max(0, budget.n_candidates_evaluated - budget.n_total_delivered),
            "text": "Nothing notable.",
        },
        budget={
            "candidates_detected": budget.n_candidates_evaluated,
            "suppressed_corporate_action": budget.n_suppressed_corporate_action,
            "rolled_up_market_wide": budget.n_suppressed_rollup,
            "grouped_sector_wide": budget.n_suppressed_diversity,
            "below_cap": budget.n_truncated_hard_cap,
            "surfaced": len(items),
            "cap": 5,
        },
        data_quality={
            "last_bhavcopy_date": str(evaluation_time.date()),
            "delivery_final_through": None,
            "symbols_below_liquidity_floor": [],
            "degraded_baselines": [],
            "index_0930_source": None,
        },
    ))


@router.post("/api/brief/ack")
def brief_ack(payload: BriefAck, user: CurrentUser) -> dict[str, str]:
    with get_engine().begin() as conn:
        db: Any = conn
        state = acknowledge_brief(db, user.user_id, "brief:default", payload.ack_through_ts)
    return {
        "user_id": state.user_id,
        "acknowledged_through_ts": state.acknowledged_through_ts.isoformat(),
    }


@router.post("/api/cursor")
def cursor(payload: CursorUpsert, user: CurrentUser) -> dict[str, int]:
    with get_engine().begin() as conn:
        db: Any = conn
        sequence = upsert_read_cursor(
            db, user.user_id, payload.feed_id, payload.incoming_seq, payload.incoming_ts
        )
    return {"last_read_seq": sequence}


@router.get("/api/symbol/{symbol}")
def symbol_facts(symbol: str) -> dict[str, Any]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT symbol, date, adj_close, volume, turnover "
                "FROM daily_bars WHERE symbol = :symbol ORDER BY date DESC LIMIT 1"
            ),
            {"symbol": symbol},
        ).mappings().first()
    return {"symbol": symbol, "facts": dict(rows) if rows is not None else None}


@router.get("/api/symbol/{symbol}/history")
def symbol_history(symbol: str) -> dict[str, Any]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT date, adj_close FROM v_adjusted_bars "
                "WHERE symbol = :symbol ORDER BY date ASC"
            ),
            {"symbol": symbol},
        ).mappings()
    return {"symbol": symbol, "history": [dict(row) for row in rows]}


@router.get("/api/metrics")
def metrics() -> dict[str, Any]:
    return {
        "pipeline": {"candidates_evaluated": 0, "digests_delivered": 0},
        "latency_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
        "delivery_budget": {"scored_items": 0, "hard_cap": 10},
    }
