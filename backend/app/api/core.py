"""Phase 9 REST resources."""

import math
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.analytics.digest import BriefPayload, build_digest
from app.analytics.digest.copy import DataStatus, render_candidate_copy
from app.api.auth import UserContext, get_current_user
from app.constants import BRIEF_MAX_ITEMS, MPM_TIER_THRESHOLDS
from app.crud.brief_cursor import EPOCH, acknowledge_brief, get_brief_cursor
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


def _get_or_create_watchlist(conn: Any, user_id: str) -> str:
    row = conn.execute(
        sa.text("SELECT id FROM watchlists WHERE user_id = :user_id AND name = 'Default'"),
        {"user_id": user_id},
    ).scalar()
    if row is not None:
        return str(row)
    watchlist_id = str(uuid4())
    conn.execute(
        sa.text("INSERT INTO watchlists (id, user_id, name) VALUES (:id, :user_id, 'Default')"),
        {"id": watchlist_id, "user_id": user_id},
    )
    return watchlist_id


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


@router.get("/api/me")
def me(user: CurrentUser) -> dict[str, Any]:
    with get_engine().begin() as conn:
        watchlist_id = _get_or_create_watchlist(conn, user.user_id)
        db: Any = conn
        cursor = get_brief_cursor(db, user.user_id)
    acknowledged_through = (
        cursor.acknowledged_through_ts.isoformat() if cursor is not None else EPOCH.isoformat()
    )
    name_parts = user.user_id.replace("_", " ").split()[:2]
    initials = "".join(part[0] for part in name_parts).upper() or "U"
    return {
        "user": {
            "id": user.user_id,
            "display_name": user.user_id.replace("_", " ").title(),
            "initials": initials,
            "is_demo": user.is_demo,
        },
        "default_watchlist_id": watchlist_id,
        "cursor": {
            "acknowledged_through": acknowledged_through,
            "sessions_elapsed": 0,
            "calendar_days_elapsed": 0,
        },
    }


@router.get("/api/market/calendar")
def market_calendar(
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    start = date.fromisoformat(from_) if from_ else today - timedelta(days=400)
    end = date.fromisoformat(to) if to else today
    with get_engine().connect() as conn:
        calendar = load_trading_calendar(conn, start, end)
    sessions = [
        {"date": str(session_date), "session_type": session.session_type}
        for session_date, session in sorted(calendar.sessions.items())
        if session.is_trading_day
    ]
    return {"window": {"from": str(start), "to": str(end)}, "sessions": sessions}


def _mpm_threshold(adj_prev_close: float) -> float:
    for upper_bound, threshold_pct in MPM_TIER_THRESHOLDS:
        if adj_prev_close < upper_bound:
            return threshold_pct / 100.0
    return MPM_TIER_THRESHOLDS[-1][1] / 100.0


def _enrich_items(
    conn: Any, payload: BriefPayload, evaluation_time: datetime
) -> list[dict[str, Any]]:
    """Join scored candidates back to their day's real numbers for copy + metrics."""
    keys = [(item.candidate.symbol, item.candidate.date) for item in payload.scored_items]
    daily_by_key: dict[tuple[str, Any], Any] = {}
    turnover_by_key: dict[tuple[str, Any], Any] = {}
    delivery_by_key: dict[tuple[str, Any], Any] = {}
    extremes_by_key: dict[tuple[str, Any], Any] = {}
    announcement_by_hash: dict[str, Any] = {}
    if keys:
        symbols = list({key[0] for key in keys})
        dates = list({key[1] for key in keys})
        rows = conn.execute(
            sa.text(
                "SELECT symbol, date, close, prev_close, turnover "
                "FROM daily_bars WHERE symbol = ANY(:symbols) AND date = ANY(:dates)"
            ),
            {"symbols": symbols, "dates": dates},
        ).mappings()
        daily_by_key = {(row["symbol"], row["date"]): row for row in rows}

        rows = conn.execute(
            sa.text(
                "SELECT symbol, date, mean_log_turnover, std_log_turnover "
                "FROM turnover_baselines WHERE symbol = ANY(:symbols) AND date = ANY(:dates)"
            ),
            {"symbols": symbols, "dates": dates},
        ).mappings()
        turnover_by_key = {(row["symbol"], row["date"]): row for row in rows}

        rows = conn.execute(
            sa.text(
                "SELECT symbol, date, raw_delivery_pct "
                "FROM delivery_baselines WHERE symbol = ANY(:symbols) AND date = ANY(:dates)"
            ),
            {"symbols": symbols, "dates": dates},
        ).mappings()
        delivery_by_key = {(row["symbol"], row["date"]): row for row in rows}

        rows = conn.execute(
            sa.text(
                "SELECT symbol, date, high_52w, low_52w, distance_to_52w_high_pct, "
                "distance_to_52w_low_pct FROM market_extremes_adv "
                "WHERE symbol = ANY(:symbols) AND date = ANY(:dates)"
            ),
            {"symbols": symbols, "dates": dates},
        ).mappings()
        extremes_by_key = {(row["symbol"], row["date"]): row for row in rows}

        all_hashes = [
            str(h) for item in payload.scored_items for h in item.candidate.linked_announcement_ids
        ]
        if all_hashes:
            rows = conn.execute(
                sa.text(
                    "SELECT id, content_hash, subject, filed_at "
                    "FROM announcements WHERE content_hash = ANY(:hashes)"
                ),
                {"hashes": all_hashes},
            ).mappings()
            announcement_by_hash = {row["content_hash"]: row for row in rows}

    items: list[dict[str, Any]] = []
    for index, item in enumerate(payload.scored_items, start=1):
        candidate = item.candidate
        key = (candidate.symbol, candidate.date)
        daily = daily_by_key.get(key)
        turnover_row = turnover_by_key.get(key)
        delivery_row = delivery_by_key.get(key)
        extremes_row = extremes_by_key.get(key)

        pct_move = 0.0
        prev_close = 0.0
        turnover_cr = None
        turnover_multiple = None
        if daily is not None and daily["prev_close"]:
            prev_close = float(daily["prev_close"])
            pct_move = (float(daily["close"]) - prev_close) / prev_close * 100.0
            if daily["turnover"] is not None:
                turnover_cr = float(daily["turnover"]) / 1e7
        if turnover_row is not None and daily is not None and daily["turnover"] is not None:
            adv = math.expm1(float(turnover_row["mean_log_turnover"]))
            turnover_multiple = float(daily["turnover"]) / adv if adv > 0 else None

        delivery_pct = float(delivery_row["raw_delivery_pct"]) if delivery_row is not None else None

        is_extreme = any(f.value == "EXTREME_52W" for f in candidate.signal_families)
        extreme_type = price = distance_pct = None
        if is_extreme and extremes_row is not None:
            near_high = abs(float(extremes_row["distance_to_52w_high_pct"])) <= abs(
                float(extremes_row["distance_to_52w_low_pct"])
            )
            extreme_type = "52-week high" if near_high else "52-week low"
            price = float(daily["close"]) if daily is not None else None
            distance_pct = float(
                extremes_row["distance_to_52w_high_pct"]
                if near_high
                else extremes_row["distance_to_52w_low_pct"]
            )

        category_label = announcement_headline = None
        linked_ids: list[int] = []
        if candidate.is_explained:
            for content_hash in candidate.linked_announcement_ids:
                row = announcement_by_hash.get(str(content_hash))
                if row is not None:
                    linked_ids.append(int(row["id"]))
                    if announcement_headline is None:
                        announcement_headline = row["subject"]
            if candidate.primary_category:
                category_label = candidate.primary_category.replace("_", " ").title()

        mechanism_label = None
        classification = "EXPLAINED" if candidate.is_explained else "UNEXPLAINED"
        for market_rollup in payload.market_rollups:
            if candidate.symbol in market_rollup.symbols:
                classification = "MARKET_WIDE"
                mechanism_label = market_rollup.benchmark_symbol
        for sector_rollup in payload.sector_rollups:
            if candidate.symbol in sector_rollup.affected_symbols:
                classification = "SECTOR_WIDE"
                mechanism_label = sector_rollup.sector

        try:
            rendered = render_candidate_copy(
                candidate,
                return_pct=pct_move,
                as_of_time=evaluation_time.strftime("%H:%M"),
                status=DataStatus.FINAL if candidate.status == "FINAL" else DataStatus.PROVISIONAL,
                turnover_cr=turnover_cr,
                turnover_multiple=turnover_multiple,
                delivery_pct=delivery_pct,
                extreme_type=extreme_type,
                price=price,
                distance_pct=distance_pct,
                category_label=category_label,
                announcement_headline=announcement_headline,
                mechanism_label=mechanism_label,
            )
        except ValueError:
            # A real filing subject interpolated into the driver line hit the
            # banned-word lint (R12) — the same "reject to template" rule
            # Task 8.6 uses for generated text applies here: fall back to a
            # sanitized label rather than 500ing the whole Brief.
            rendered = render_candidate_copy(
                candidate,
                return_pct=pct_move,
                as_of_time=evaluation_time.strftime("%H:%M"),
                status=DataStatus.FINAL if candidate.status == "FINAL" else DataStatus.PROVISIONAL,
                turnover_cr=turnover_cr,
                turnover_multiple=turnover_multiple,
                delivery_pct=delivery_pct,
                extreme_type=extreme_type,
                price=price,
                distance_pct=distance_pct,
                category_label=category_label if candidate.is_explained else None,
                announcement_headline="an exchange filing" if candidate.is_explained else None,
                mechanism_label=mechanism_label,
            )

        turnover_dominates = candidate.turnover_z is not None and abs(
            candidate.turnover_z
        ) >= abs(candidate.delivery_z or 0)
        family = (
            "TURNOVER_SURGE"
            if turnover_dominates
            else "DELIVERY_SHIFT"
            if candidate.delivery_z is not None
            else "PRICE_MOVE"
        )
        mpm_threshold = _mpm_threshold(prev_close) if prev_close else 0.0

        items.append(
            {
                "signal_event_id": candidate.id or f"{candidate.date}:{candidate.symbol}",
                "symbol": candidate.symbol,
                "company_name": candidate.symbol,
                "family": family,
                "classification": classification,
                "rank": index,
                "score": item.final_score,
                "what": rendered.headline,
                "how_unusual": rendered.statistical_context,
                "cause": rendered.driver,
                "freshness": rendered.status_stamp,
                "metrics": {
                    "pct_move": pct_move,
                    "scar": candidate.sar,
                    "turnover_z": candidate.turnover_z or 0.0,
                    "delivery_z": candidate.delivery_z or 0.0,
                    "delivery_pct": delivery_pct or 0.0,
                    "mpm_triggered": any(
                        f.value in ("PRICE_MPM", "INTRADAY_SWING")
                        for f in candidate.signal_families
                    ),
                    "mpm_threshold_used": mpm_threshold,
                },
                "provisional": candidate.status != "FINAL",
                "revision": candidate.revision,
                "was_restated": candidate.was_restated,
                "completeness": [],
                "linked_announcement_ids": linked_ids,
                "links": {
                    "announcement": None,
                    "explain": f"/api/brief/explain/{candidate.id or candidate.symbol}",
                },
            }
        )
    return items


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
    # build_digest's record_brief_served commits internally, which desyncs the
    # begin()-owned transaction above for any further use of that connection —
    # the read-only enrichment join gets its own, separate connection.
    with get_engine().connect() as conn:
        items = _enrich_items(conn, payload, evaluation_time)

    budget = payload.budget
    assert budget is not None
    market_rollup_text = "; ".join(rollup.summary_text for rollup in payload.market_rollups)
    market_index_change = (
        payload.market_rollups[0].benchmark_return if payload.market_rollups else 0.0
    )
    market_symbols = [
        symbol for rollup in payload.market_rollups for symbol in rollup.symbols
    ]
    return BriefResponse.model_validate(dict(
        generated_at=evaluation_time.isoformat(),
        cursor={
            "acknowledged_through": payload.cursor_ack_ts.isoformat(),
            "sessions_elapsed": 0,
            "calendar_days_elapsed": 0,
        },
        headline=(
            f"Since your last read, {len(items)} things changed."
            if items
            else "Since your last read, nothing crossed the bar."
        ),
        market_rollup={
            "present": bool(payload.market_rollups),
            "text": market_rollup_text,
            "index_change_pct": market_index_change * 100.0,
            "symbols_attributed": market_symbols,
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
            "rolled_up_market_wide": budget.n_market_rollups,
            "grouped_sector_wide": budget.n_sector_rollups,
            "below_cap": budget.n_truncated_hard_cap,
            "surfaced": len(items),
            "cap": BRIEF_MAX_ITEMS,
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
    with get_engine().connect() as conn:
        candidates_evaluated = conn.execute(sa.text("SELECT COUNT(*) FROM candidates")).scalar_one()
        digests_delivered = conn.execute(
            sa.text("SELECT COUNT(*) FROM digest_deliveries")
        ).scalar_one() if "digest_deliveries" in sa.inspect(conn).get_table_names() else 0
    return {
        "pipeline": {
            "candidates_evaluated": int(candidates_evaluated),
            "digests_delivered": int(digests_delivered),
        },
        "latency_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
        "delivery_budget": {"scored_items": 0, "hard_cap": BRIEF_MAX_ITEMS},
    }
