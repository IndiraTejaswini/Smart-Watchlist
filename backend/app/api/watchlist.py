"""Watchlist CRUD endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Any
from uuid import uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from app.analytics.fractional_index import (
    generate_midpoint_position,
    should_trigger_rebalance,
)
from app.analytics.watchlist_rebalancer import rebalance_watchlist
from app.api.idempotency import (
    CachedResponse,
    load_cached_response,
    store_response,
)
from app.crud.watchlist import update_watchlist
from app.db import get_engine

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def connection() -> Iterator[sa.Connection]:
    with get_engine().begin() as conn:
        yield conn


Connection = Annotated[sa.Connection, Depends(connection)]


class WatchlistItemRequest(BaseModel):
    symbol: str
    after_symbol: str | None = None
    before_symbol: str | None = None


class WatchlistUpdateRequest(BaseModel):
    name: str


class WatchlistItemReorderRequest(BaseModel):
    after_symbol: str | None = None
    before_symbol: str | None = None


def parse_if_match_header(if_match: str | None = Header(None)) -> int:
    if not if_match or not if_match.strip():
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="If-Match header is required for mutating operations.",
        )
    value = if_match.strip()
    if value.startswith("W/"):
        value = value[2:].strip()
    value = value.strip('"')
    try:
        return int(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid If-Match version") from exc


def _user_id(user_id: str | None) -> str:
    if not user_id:
        raise HTTPException(status_code=400, detail="X-User-ID header is required")
    return user_id


def _watchlist(conn: sa.Connection, user_id: str) -> str:
    row = conn.execute(
        sa.text("SELECT id FROM watchlists WHERE user_id = :user_id AND name = 'Default'"),
        {"user_id": user_id},
    ).scalar()
    if row is not None:
        return str(row)
    watchlist_id = str(uuid4())
    conn.execute(
        sa.text(
            "INSERT INTO watchlists (id, user_id, name) "
            "VALUES (:id, :user_id, 'Default')"
        ),
        {"id": watchlist_id, "user_id": user_id},
    )
    return watchlist_id


@router.get("")
def get_watchlist(
    conn: Connection,
    x_user_id: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    user_id = _user_id(x_user_id)
    watchlist_id = _watchlist(conn, user_id)
    rows = conn.execute(
        sa.text(
            "SELECT symbol, position FROM watchlist_items "
            "WHERE watchlist_id = :watchlist_id ORDER BY position ASC"
        ),
        {"watchlist_id": watchlist_id},
    ).mappings()
    return {"items": [dict(row) for row in rows]}


@router.get("/{watchlist_id}")
def get_watchlist_by_id(
    watchlist_id: str,
    conn: Connection,
) -> Response:
    row = conn.execute(
        sa.text(
            "SELECT id, user_id, name, version, created_at, updated_at "
            "FROM watchlists WHERE id = :watchlist_id"
        ),
        {"watchlist_id": watchlist_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    # The frontend's useWatchlistItems calls this route (not the bare
    # GET /api/watchlist above) and needs `items` in the same shape that one
    # returns — without it the Lists page's schema validation fails and the
    # page renders "could not be loaded" with 0 names, regardless of how many
    # symbols are actually on the list.
    item_rows = conn.execute(
        sa.text(
            "SELECT symbol, position FROM watchlist_items "
            "WHERE watchlist_id = :watchlist_id ORDER BY position ASC"
        ),
        {"watchlist_id": watchlist_id},
    ).mappings()
    body = {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "name": row["name"],
        "version": int(row["version"]),
        "items": [dict(item) for item in item_rows],
    }
    return Response(
        content=__import__("json").dumps(body, default=str),
        headers={"ETag": f'"{row["version"]}"'},
        media_type="application/json",
    )


@router.get("/{watchlist_id}/quotes")
def watchlist_quotes(watchlist_id: str, conn: Connection) -> dict[str, Any]:
    """The Lists page's price columns, from the last real session — not a
    live tick.

    This build has no broker feed and no live NSE session to poll against a
    frozen, pre-seeded dataset (§19), so there is no honest sense in which a
    number here is "live." What is real and available is each symbol's own
    latest daily_bars row, which is exactly what this returns — final,
    end-of-day figures, the same "Bhavcopy final" data the rest of the app
    already shows.
    """
    symbols = conn.execute(
        sa.text("SELECT symbol FROM watchlist_items WHERE watchlist_id = :watchlist_id"),
        {"watchlist_id": watchlist_id},
    ).scalars().all()
    if not symbols:
        return {"quotes": {}}

    rows = conn.execute(
        sa.text(
            "WITH latest_bars AS ("
            "  SELECT DISTINCT ON (symbol) symbol, date, close, prev_close, turnover "
            "  FROM daily_bars WHERE symbol = ANY(:symbols) "
            "  ORDER BY symbol, date DESC"
            ") "
            "SELECT lb.symbol, lb.date, lb.close, lb.prev_close, lb.turnover, "
            "ds.delivery_pct "
            "FROM latest_bars lb "
            "LEFT JOIN delivery_stats ds ON ds.symbol = lb.symbol AND ds.date = lb.date"
        ),
        {"symbols": list(symbols)},
    ).mappings()

    quotes: dict[str, Any] = {}
    for row in rows:
        close = float(row["close"])
        prev_close = float(row["prev_close"]) if row["prev_close"] is not None else close
        change = close - prev_close
        chp = (change / prev_close * 100) if prev_close else 0.0
        turnover_cr = float(row["turnover"] or 0) / 1e7
        quotes[row["symbol"]] = {
            "ltp": close,
            "change": change,
            "chp": chp,
            "turnover": turnover_cr,
            "delivery": float(row["delivery_pct"]) if row["delivery_pct"] is not None else None,
            "as_of_date": str(row["date"]),
            "freshness": "final",
            "state": "FINAL",
        }
    return {"quotes": quotes}


@router.get("/{watchlist_id}/signals")
def watchlist_signals(
    watchlist_id: str,
    conn: Connection,
    symbol: str | None = None,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: str | None = None,
) -> dict[str, Any]:
    """Signal marks for the cursor spine (§3) — one row per candidate day.

    "surfaced" means a real candidate existed for that symbol-date (it
    cleared the MPM gate and abnormality thresholds), not that a specific
    Brief delivered it — there is no per-user, per-item delivery ledger to
    read that back from.
    """
    symbols_row = conn.execute(
        sa.text("SELECT symbol FROM watchlist_items WHERE watchlist_id = :watchlist_id"),
        {"watchlist_id": watchlist_id},
    ).scalars()
    symbols = [symbol] if symbol else list(symbols_row)
    if not symbols:
        return {"watchlist_id": watchlist_id, "marks": []}

    clauses = ["symbol = ANY(:symbols)"]
    params: dict[str, Any] = {"symbols": symbols}
    if from_:
        clauses.append("date >= :from_date")
        params["from_date"] = from_
    if to:
        clauses.append("date <= :to_date")
        params["to_date"] = to
    rows = conn.execute(
        sa.text(
            "SELECT id, date, symbol FROM candidates WHERE " + " AND ".join(clauses)
        ),
        params,
    ).mappings()
    marks = [
        {
            "signal_event_id": row["id"] or f"{row['date']}:{row['symbol']}",
            "session_date": str(row["date"]),
            "symbol": row["symbol"],
            "surfaced": True,
        }
        for row in rows
    ]
    return {"watchlist_id": watchlist_id, "marks": marks}


@router.put("/{watchlist_id}")
def update_watchlist_endpoint(
    watchlist_id: str,
    payload: WatchlistUpdateRequest,
    conn: Connection,
    if_match: Annotated[str | None, Header()] = None,
) -> Response:
    expected_version = parse_if_match_header(if_match)
    updated = update_watchlist(conn, watchlist_id, payload.name, expected_version)
    body = {
        "id": updated.id,
        "user_id": updated.user_id,
        "name": updated.name,
        "version": updated.version,
    }
    return Response(
        content=__import__("json").dumps(body),
        headers={"ETag": f'"{updated.version}"'},
        media_type="application/json",
    )


@router.post("/items", status_code=201)
def add_watchlist_item(
    payload: WatchlistItemRequest,
    request: Request,
    conn: Connection,
    x_user_id: Annotated[str | None, Header()] = None,
    redis_client: Any | None = None,
) -> Response:
    user_id = _user_id(x_user_id)
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")
    if redis_client is not None:
        cached = load_cached_response(redis_client, user_id, key)
        if cached is not None:
            return Response(
                content=__import__("json").dumps(cached.body),
                status_code=cached.status_code,
                headers=cached.headers,
                media_type="application/json",
            )
    watchlist_id = _watchlist(conn, user_id)
    previous = conn.execute(
        sa.text(
            "SELECT position FROM watchlist_items WHERE watchlist_id = :watchlist_id "
            "AND symbol = :symbol"
        ),
        {"watchlist_id": watchlist_id, "symbol": payload.after_symbol},
    ).scalar() if payload.after_symbol else None
    following = conn.execute(
        sa.text(
            "SELECT position FROM watchlist_items WHERE watchlist_id = :watchlist_id "
            "AND symbol = :symbol"
        ),
        {"watchlist_id": watchlist_id, "symbol": payload.before_symbol},
    ).scalar() if payload.before_symbol else None
    position = generate_midpoint_position(
        Decimal(str(previous)) if previous is not None else None,
        Decimal(str(following)) if following is not None else None,
    )
    item = {"id": str(uuid4()), "symbol": payload.symbol, "position": str(position)}
    conn.execute(
        sa.text(
            "INSERT INTO watchlist_items (id, watchlist_id, symbol, position) "
            "VALUES (:id, :watchlist_id, :symbol, :position)"
        ),
        {"id": item["id"], "watchlist_id": watchlist_id, **item},
    )
    if should_trigger_rebalance(position) and redis_client is not None:
        rebalance_watchlist(conn, redis_client, watchlist_id)
    response_body = {"item": item}
    if redis_client is not None:
        store_response(redis_client, user_id, key, CachedResponse(201, {}, response_body))
    return Response(
        content=__import__("json").dumps(response_body),
        status_code=201,
        media_type="application/json",
    )


@router.patch("/items/{symbol}/position")
def reorder_watchlist_item(
    symbol: str,
    payload: WatchlistItemReorderRequest,
    conn: Connection,
    x_user_id: Annotated[str | None, Header()] = None,
    redis_client: Any | None = None,
) -> dict[str, str]:
    """Drag-to-reorder (12.6, Task 7.3/7.4's fractional index applied to a
    move rather than an insert): re-key one existing item between two others,
    rewriting nothing else in the list."""
    user_id = _user_id(x_user_id)
    watchlist_id = _watchlist(conn, user_id)
    owns_symbol = conn.execute(
        sa.text(
            "SELECT 1 FROM watchlist_items WHERE watchlist_id = :watchlist_id AND symbol = :symbol"
        ),
        {"watchlist_id": watchlist_id, "symbol": symbol},
    ).first()
    if owns_symbol is None:
        raise HTTPException(status_code=404, detail="Symbol not on this watchlist")

    def _position_of(other_symbol: str | None) -> Decimal | None:
        if not other_symbol:
            return None
        value = conn.execute(
            sa.text(
                "SELECT position FROM watchlist_items "
                "WHERE watchlist_id = :watchlist_id AND symbol = :symbol"
            ),
            {"watchlist_id": watchlist_id, "symbol": other_symbol},
        ).scalar()
        return Decimal(str(value)) if value is not None else None

    position = generate_midpoint_position(
        _position_of(payload.after_symbol), _position_of(payload.before_symbol)
    )
    conn.execute(
        sa.text(
            "UPDATE watchlist_items SET position = :position "
            "WHERE watchlist_id = :watchlist_id AND symbol = :symbol"
        ),
        {"position": str(position), "watchlist_id": watchlist_id, "symbol": symbol},
    )
    if should_trigger_rebalance(position) and redis_client is not None:
        rebalance_watchlist(conn, redis_client, watchlist_id)
    return {"symbol": symbol, "position": str(position)}


@router.delete("/items/{symbol}")
def delete_watchlist_item(
    symbol: str,
    conn: Connection,
    x_user_id: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    user_id = _user_id(x_user_id)
    conn.execute(
        sa.text(
            "DELETE FROM watchlist_items WHERE symbol = :symbol AND watchlist_id IN "
            "(SELECT id FROM watchlists WHERE user_id = :user_id AND name = 'Default')"
        ),
        {"symbol": symbol, "user_id": user_id},
    )
    return {"deleted": True}
