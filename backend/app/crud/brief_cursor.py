"""Delivered-versus-acknowledged brief cursor persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class BriefCursorState:
    user_id: str
    feed_id: str
    seen_through_ts: datetime
    acknowledged_through_ts: datetime
    updated_at: datetime


def _state_from_row(row: sa.RowMapping) -> BriefCursorState:
    return BriefCursorState(
        user_id=str(row["user_id"]),
        feed_id=str(row["feed_id"]),
        seen_through_ts=row["seen_through_ts"],
        acknowledged_through_ts=row["acknowledged_through_ts"],
        updated_at=row["updated_at"],
    )


def get_brief_cursor(
    db: Session, user_id: str, feed_id: str = "brief:default"
) -> BriefCursorState | None:
    row = db.execute(
        sa.text(
            "SELECT user_id, feed_id, seen_through_ts, acknowledged_through_ts, updated_at "
            "FROM brief_cursor_states WHERE user_id = :user_id AND feed_id = :feed_id"
        ),
        {"user_id": user_id, "feed_id": feed_id},
    ).mappings().first()
    return None if row is None else _state_from_row(row)


def record_brief_served(
    db: Session,
    user_id: str,
    feed_id: str,
    served_through_ts: datetime,
) -> BriefCursorState:
    row = db.execute(
        sa.text(
            "INSERT INTO brief_cursor_states "
            "(user_id, feed_id, seen_through_ts, acknowledged_through_ts, updated_at) "
            "VALUES (:user_id, :feed_id, :served_through_ts, :epoch, NOW()) "
            "ON CONFLICT (user_id, feed_id) DO UPDATE SET "
            "seen_through_ts = GREATEST(brief_cursor_states.seen_through_ts, "
            "EXCLUDED.seen_through_ts), updated_at = NOW() RETURNING *"
        ),
        {
            "user_id": user_id,
            "feed_id": feed_id,
            "served_through_ts": served_through_ts,
            "epoch": EPOCH,
        },
    ).mappings().one()
    db.commit()
    return _state_from_row(row)


def acknowledge_brief(
    db: Session,
    user_id: str,
    feed_id: str,
    ack_through_ts: datetime,
) -> BriefCursorState:
    row = db.execute(
        sa.text(
            "INSERT INTO brief_cursor_states "
            "(user_id, feed_id, seen_through_ts, acknowledged_through_ts, updated_at) "
            "VALUES (:user_id, :feed_id, :ack_through_ts, :ack_through_ts, NOW()) "
            "ON CONFLICT (user_id, feed_id) DO UPDATE SET "
            "acknowledged_through_ts = GREATEST("
            "brief_cursor_states.acknowledged_through_ts, EXCLUDED.acknowledged_through_ts), "
            "seen_through_ts = GREATEST("
            "brief_cursor_states.seen_through_ts, EXCLUDED.acknowledged_through_ts), "
            "updated_at = NOW() RETURNING *"
        ),
        {
            "user_id": user_id,
            "feed_id": feed_id,
            "ack_through_ts": ack_through_ts,
        },
    ).mappings().one()
    db.commit()
    return _state_from_row(row)
