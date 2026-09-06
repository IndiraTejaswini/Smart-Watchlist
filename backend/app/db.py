"""Database engine — ARCHITECTURE.md §4.1.

One engine per process, built from `app.config`. Nothing here knows any schema:
migrations own the DDL (`alembic/versions/`) and each module writes its own SQL,
because §5-§20 is the specification and an ORM model would quietly become a
second, competing one.
"""

from __future__ import annotations

from functools import lru_cache

import sqlalchemy as sa

from app.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> sa.Engine:
    return sa.create_engine(get_settings().DATABASE_URL, future=True)
