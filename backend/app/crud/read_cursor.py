"""Atomic monotonic read-cursor persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ReadCursor:
    user_id: str
    feed_id: str
    last_read_seq: int
    last_read_at: datetime
    updated_at: datetime


def upsert_read_cursor(
    db: Session,
    user_id: str,
    feed_id: str,
    incoming_seq: int,
    incoming_ts: datetime,
) -> int:
    """Merge a cursor atomically, retaining the greatest sequence number."""
    result = db.execute(
        sa.text(
            "INSERT INTO read_cursors "
            "(user_id, feed_id, last_read_seq, last_read_at, updated_at) "
            "VALUES (:user_id, :feed_id, :incoming_seq, :incoming_ts, NOW()) "
            "ON CONFLICT (user_id, feed_id) DO UPDATE SET "
            "last_read_seq = GREATEST(read_cursors.last_read_seq, EXCLUDED.last_read_seq), "
            "last_read_at = CASE WHEN EXCLUDED.last_read_seq >= read_cursors.last_read_seq "
            "THEN EXCLUDED.last_read_at ELSE read_cursors.last_read_at END, "
            "updated_at = NOW() "
            "RETURNING last_read_seq"
        ),
        {
            "user_id": user_id,
            "feed_id": feed_id,
            "incoming_seq": incoming_seq,
            "incoming_ts": incoming_ts,
        },
    )
    effective_seq = result.scalar_one()
    db.commit()
    return int(effective_seq)


def get_read_cursor(db: Session, user_id: str, feed_id: str) -> ReadCursor | None:
    """Fetch one persisted cursor, or ``None`` when it has not been created."""
    row = db.execute(
        sa.text(
            "SELECT user_id, feed_id, last_read_seq, last_read_at, updated_at "
            "FROM read_cursors WHERE user_id = :user_id AND feed_id = :feed_id"
        ),
        {"user_id": user_id, "feed_id": feed_id},
    ).mappings().first()
    if row is None:
        return None
    return ReadCursor(
        user_id=str(row["user_id"]),
        feed_id=str(row["feed_id"]),
        last_read_seq=int(row["last_read_seq"]),
        last_read_at=row["last_read_at"],
        updated_at=row["updated_at"],
    )
