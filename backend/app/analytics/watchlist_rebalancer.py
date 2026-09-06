"""Single-flight fractional-position rebalancing."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import sqlalchemy as sa

LOCK_TTL_SECONDS = 60


def rebalance_watchlist(
    db: Any,
    redis_client: Any | None,
    watchlist_id: str,
) -> bool:
    """Rewrite only the target list's positions while holding a short lock."""
    lock_key = f"watchlist:rebalance:lock:{watchlist_id}"
    lock_acquired = True
    if redis_client is not None:
        lock_acquired = bool(redis_client.set(lock_key, "1", nx=True, ex=LOCK_TTL_SECONDS))
    if not lock_acquired:
        return False
    try:
        rows = db.execute(
            sa.text(
                "SELECT id, position FROM watchlist_items "
                "WHERE watchlist_id = :watchlist_id ORDER BY position ASC FOR UPDATE"
            ),
            {"watchlist_id": watchlist_id},
        ).mappings().all()
        for index, row in enumerate(rows, 1):
            db.execute(
                sa.text(
                    "UPDATE watchlist_items SET position = :position WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "position": Decimal(index * 1000).quantize(
                        Decimal("1.0000000000000000")
                    ),
                },
            )
        if hasattr(db, "commit"):
            db.commit()
        return True
    finally:
        if redis_client is not None:
            redis_client.delete(lock_key)
