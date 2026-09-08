"""Polling fallback quotes endpoint."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from redis import Redis

from app.config import get_settings
from app.crud.quotes import fetch_quotes_batch
from app.db import get_engine
from app.schemas.quote import QuotesListResponse

router = APIRouter(prefix="/api", tags=["quotes"])


@router.get("/quotes", response_model=QuotesListResponse)
def quotes(
    symbols: Annotated[str, Query(description="Comma-separated ticker list")],
) -> QuotesListResponse:
    symbols_list = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    if not symbols_list:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Symbols parameter cannot be empty.")
    if len(symbols_list) > 100:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Maximum 100 symbols permitted per request.")
    now = datetime.now(UTC)
    redis_client = Redis.from_url(
        get_settings().REDIS_URL, decode_responses=False, socket_connect_timeout=2
    )
    with get_engine().connect() as conn:
        from app.timeutil import TradingCalendar

        calendar = TradingCalendar.from_rows(
            [{"calendar_date": now.date(), "is_trading_day": True, "session_type": "REGULAR"}]
        )
        quotes_list = fetch_quotes_batch(conn, redis_client, symbols_list, now, calendar)
    return QuotesListResponse(as_of=now, quotes=quotes_list)
