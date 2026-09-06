"""Read-time adjustment-factor recomputation for one isolated symbol."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from app.db import get_engine

ONE = Decimal("1")


def _recompute(conn: Any, symbol: str) -> int:
    dates = list(
        conn.execute(
            sa.text(
                "SELECT date FROM daily_bars WHERE symbol = :symbol "
                "ORDER BY date DESC"
            ),
            {"symbol": symbol},
        ).scalars()
    )
    actions = conn.execute(
        sa.text(
            "SELECT ex_date, action_type, price_factor, tr_factor "
            "FROM corporate_actions WHERE symbol = :symbol "
            "AND verification = 'VERIFIED' ORDER BY ex_date DESC"
        ),
        {"symbol": symbol},
    ).mappings()
    by_date: dict[date, list[dict[str, object]]] = {}
    for action_row in actions:
        action_data = dict(action_row)
        by_date.setdefault(action_data["ex_date"], []).append(action_data)

    conn.execute(
        sa.text("DELETE FROM symbol_adjustment_factors WHERE symbol = :symbol"),
        {"symbol": symbol},
    )
    price_factor = ONE
    tr_factor = ONE
    volume_factor = ONE
    rows: list[dict[str, object]] = []
    for trading_date in dates:
        rows.append(
            {
                "symbol": symbol,
                "date": trading_date,
                "cum_price_factor": price_factor,
                "cum_tr_factor": tr_factor,
                "cum_vol_factor": volume_factor,
            }
        )
        for action in by_date.get(trading_date, []):
            action_price = Decimal(str(action["price_factor"] or ONE))
            action_tr = Decimal(str(action["tr_factor"] or ONE))
            price_factor *= action_price
            tr_factor *= action_tr
            if action["action_type"] in {"BONUS", "SPLIT", "CONSOLIDATION", "RIGHTS"}:
                volume_factor *= ONE / action_price

    if rows:
        conn.execute(
            sa.text(
                "INSERT INTO symbol_adjustment_factors "
                "(symbol, date, cum_price_factor, cum_tr_factor, cum_vol_factor) "
                "VALUES (:symbol, :date, :cum_price_factor, :cum_tr_factor, :cum_vol_factor)"
            ),
            rows,
        )
    return len(rows)


def recompute_symbol_adjustment_factors(
    db: sa.Engine | sa.Connection | Any | None, symbol: str
) -> int:
    """Rebuild only ``symbol`` factors atomically and return inserted row count."""
    if not symbol.strip():
        raise ValueError("symbol must not be empty")
    if db is not None and not isinstance(db, sa.Engine):
        return _recompute(db, symbol)
    engine = db or get_engine()
    with engine.begin() as conn:
        return _recompute(conn, symbol)
