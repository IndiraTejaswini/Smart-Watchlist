"""Adjustment-aware live tick and watchlist quote enrichment."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

from app.db import get_engine

ONE = Decimal("1.0")
FOUR_PLACES = Decimal("0.0001")
TWO_PLACES = Decimal("0.01")


class AdjustmentFactorCache:
    """In-memory factors for one market session.

    The cache is loaded once per session and deliberately does not perform
    database work from ``factor`` or quote enrichment calls.
    """

    def __init__(self) -> None:
        self._session_date: date | None = None
        self._factors: dict[str, Decimal] = {}

    @property
    def session_date(self) -> date | None:
        return self._session_date

    def invalidate(self) -> None:
        self._session_date = None
        self._factors.clear()

    def load(self, conn: Any, session_date: date) -> int:
        rows = conn.execute(
            sa.text(
                "SELECT symbol, cum_price_factor "
                "FROM symbol_adjustment_factors WHERE date = :session_date"
            ),
            {"session_date": session_date},
        ).mappings()
        self._factors = {
            str(row["symbol"]): Decimal(str(row["cum_price_factor"] or ONE))
            for row in rows
        }
        self._session_date = session_date
        return len(self._factors)

    def refresh(self, session_date: date, conn: Any | None = None) -> int:
        """Load factors for a new session, replacing stale session state."""
        if conn is None:
            with get_engine().connect() as connection:
                return self.load(connection, session_date)
        return self.load(conn, session_date)

    def refresh_if_needed(self, session_date: date, conn: Any | None = None) -> bool:
        """Refresh only when the requested session differs from the cached one."""
        if self._session_date == session_date:
            return False
        self.refresh(session_date, conn)
        return True

    def factor(self, symbol: str) -> Decimal:
        return self._factors.get(symbol, ONE)


def enrich_live_tick(
    *,
    symbol: str,
    ltp: Decimal | float | str,
    raw_prev_close: Decimal | float | str,
    factor_cache: AdjustmentFactorCache,
) -> dict[str, object]:
    """Stamp a live quote with auditable raw and adjusted previous closes."""
    live_price = Decimal(str(ltp))
    raw_close = Decimal(str(raw_prev_close))
    factor = factor_cache.factor(symbol)
    adj_close = (raw_close * factor).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)
    if adj_close <= 0:
        raise ValueError("raw_prev_close and adjustment factor must produce a positive close")
    change_pct = (((live_price - adj_close) / adj_close) * 100).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    return {
        "symbol": symbol,
        "ltp": live_price,
        "raw_prev_close": raw_close,
        "adj_prev_close": adj_close,
        "cum_price_factor": factor,
        "change_pct": change_pct,
    }


def enrich_watchlist_quote(
    *,
    symbol: str,
    ltp: Decimal | float | str,
    raw_prev_close: Decimal | float | str,
    factor_cache: AdjustmentFactorCache,
) -> dict[str, object]:
    """Alias used by watchlist consumers; preserves the quote audit fields."""
    return enrich_live_tick(
        symbol=symbol,
        ltp=ltp,
        raw_prev_close=raw_prev_close,
        factor_cache=factor_cache,
    )
