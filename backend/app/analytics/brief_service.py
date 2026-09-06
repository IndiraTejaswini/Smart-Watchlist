"""Brief retrieval isolated from acknowledgement state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.crud.brief_cursor import EPOCH, BriefCursorState, get_brief_cursor, record_brief_served


@dataclass(frozen=True)
class BriefPayload:
    items: tuple[dict[str, Any], ...]
    cursor: BriefCursorState


def get_or_render_brief(
    db: Session,
    user_id: str,
    feed_id: str = "brief:default",
) -> BriefPayload:
    cursor = get_brief_cursor(db, user_id, feed_id)
    acknowledged_at = cursor.acknowledged_through_ts if cursor is not None else EPOCH
    rows = db.execute(
        sa.text(
            "SELECT * FROM candidates "
            "WHERE created_at > :acknowledged_through_ts "
            "ORDER BY created_at ASC"
        ),
        {"acknowledged_through_ts": acknowledged_at},
    ).mappings()
    items = tuple(dict(row) for row in rows)
    max_candidate_ts = (
        items[-1]["created_at"] if items else datetime.now(UTC)
    )
    served_cursor = record_brief_served(db, user_id, feed_id, max_candidate_ts)
    return BriefPayload(items=items, cursor=served_cursor)
