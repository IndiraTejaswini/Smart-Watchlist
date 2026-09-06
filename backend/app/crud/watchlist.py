"""Optimistic-concurrency watchlist mutations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException, status


@dataclass(frozen=True)
class Watchlist:
    id: str
    user_id: str
    name: str
    version: int
    created_at: datetime
    updated_at: datetime


def _watchlist(row: Any) -> Watchlist:
    return Watchlist(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        version=int(row["version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def update_watchlist(
    db: Any,
    watchlist_id: str,
    new_name: str,
    expected_version: int,
) -> Watchlist:
    row = db.execute(
        sa.text(
            "UPDATE watchlists SET name = :new_name, version = version + 1, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = :watchlist_id "
            "AND version = :expected_version "
            "RETURNING id, user_id, name, version, created_at, updated_at"
        ),
        {
            "new_name": new_name,
            "watchlist_id": watchlist_id,
            "expected_version": expected_version,
        },
    ).mappings().first()
    if row is None:
        current = db.execute(
            sa.text("SELECT version FROM watchlists WHERE id = :watchlist_id"),
            {"watchlist_id": watchlist_id},
        ).scalar()
        if current is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Resource version conflict",
                "current_version": int(current),
                "provided_version": expected_version,
            },
        )
    db.commit()
    return _watchlist(row)
