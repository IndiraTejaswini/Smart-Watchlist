"""Guarded entry points for baseline and restatement jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import TypeVar

import sqlalchemy as sa

from app.db import get_engine
from app.ingest.polling import ensure_not_escalated

T = TypeVar("T")


def run_baseline(
    target_date: date,
    compute: Callable[[sa.Connection], T],
    *,
    engine: sa.Engine | None = None,
) -> T:
    """Refuse baseline computation before invoking it for an escalated date."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        ensure_not_escalated(conn, target_date)
        return compute(conn)


def run_restatement(
    target_date: date,
    compute: Callable[[sa.Connection], T],
    *,
    engine: sa.Engine | None = None,
) -> T:
    """Apply the same fail-fast escalation guard to restatement jobs."""
    return run_baseline(target_date, compute, engine=engine)
