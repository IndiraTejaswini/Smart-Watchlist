"""Calendar-gated evening polling and escalation state machine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from app.db import get_engine
from app.ingest import runs
from app.ingest.bhavcopy import BHAVCOPY_SOURCE

SOURCE = BHAVCOPY_SOURCE
MAX_ATTEMPTS = 4
ESCALATION_TIME = time(20, 30)
IST = ZoneInfo("Asia/Kolkata")


class EscalatedIngestError(RuntimeError):
    """A dependent job attempted to use an escalated ingest date."""


@dataclass(frozen=True)
class PollResult:
    target_date: date
    trading_day: bool
    attempt: int = 0
    status: str = "SKIPPED_NON_TRADING_DAY"


def _is_trading_day(conn: sa.Connection, target_date: date) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT is_trading_day FROM trading_calendar "
            "WHERE calendar_date = :target_date"
        ),
        {"target_date": target_date},
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"trading calendar does not cover {target_date}")
    return bool(row)


def _failed_attempts(conn: sa.Connection, target_date: date) -> int:
    return int(
        conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM ingest_runs "
                "WHERE source = :source AND target_date = :target_date "
                "AND status = 'FAILED'"
            ),
            {"source": SOURCE, "target_date": target_date},
        ).scalar_one()
    )


def poll_bhavcopy(
    target_date: date,
    fetch: Callable[[], bytes],
    *,
    now: datetime | None = None,
    engine: sa.Engine | None = None,
) -> PollResult:
    """Run one evening poll, escalating only after four post-cutoff failures."""
    engine = engine or get_engine()
    now = now or datetime.now(IST)
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("poll timestamp must be timezone-aware")

    with engine.begin() as conn:
        if not _is_trading_day(conn, target_date):
            return PollResult(target_date=target_date, trading_day=False)

        previous_failures = _failed_attempts(conn, target_date)
        if previous_failures >= MAX_ATTEMPTS:
            if now.astimezone(IST).time() >= ESCALATION_TIME:
                conn.execute(
                    sa.text(
                        "UPDATE ingest_runs SET status = 'ESCALATED', finished_at = NOW() "
                        "WHERE source = :source AND target_date = :target_date "
                        "AND status = 'FAILED'"
                    ),
                    {"source": SOURCE, "target_date": target_date},
                )
                status = "ESCALATED"
            else:
                status = "FAILED"
            return PollResult(
                target_date=target_date,
                trading_day=True,
                attempt=previous_failures,
                status=status,
            )

        try:
            payload = fetch()
        except Exception as exc:
            attempt = previous_failures + 1
            run_id = runs.start_run(
                conn,
                source=SOURCE,
                target_date=target_date,
                file_hash="",
            )
            status = (
                "ESCALATED"
                if attempt >= MAX_ATTEMPTS and now.astimezone(IST).time() >= ESCALATION_TIME
                else "FAILED"
            )
            runs.finish_run(conn, run_id, status=status, rows=0, error=str(exc))
            return PollResult(
                target_date=target_date,
                trading_day=True,
                attempt=attempt,
                status=status,
            )

    if not payload:
        raise ValueError("poll fetch returned an empty payload")
    return PollResult(target_date=target_date, trading_day=True, status="RECEIVED")


def latest_escalated_dates(
    conn: sa.Connection,
    *,
    source: str = SOURCE,
) -> list[date]:
    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT target_date FROM ingest_runs "
            "WHERE source = :source AND status = 'ESCALATED' "
            "AND target_date IS NOT NULL ORDER BY target_date"
        ),
        {"source": source},
    )
    return [row[0] for row in rows]


def ensure_not_escalated(
    conn: sa.Connection, target_date: date, *, source: str = SOURCE
) -> None:
    if conn.execute(
        sa.text(
            "SELECT 1 FROM ingest_runs WHERE source = :source "
            "AND target_date = :target_date AND status = 'ESCALATED' LIMIT 1"
        ),
        {"source": source, "target_date": target_date},
    ).first():
        raise EscalatedIngestError(
            f"{source} is ESCALATED for {target_date}; dependent job refused"
        )
