"""Chronological 12-month NSE backfill runner."""

from __future__ import annotations

import argparse
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import partial
from pathlib import Path

import sqlalchemy as sa

from app.config import get_settings
from app.db import get_engine
from app.ingest import delivery, index_data
from app.ingest.bhavcopy_ingest import _fetch_payload, ingest_bhavcopy
from app.ingest.index_snapshot import capture_index_snapshot_0930
from app.ingest.nse_client import (
    NSE_BREAKER,
    CircuitOpenError,
    NSEError,
)

log = logging.getLogger(__name__)

SUCCESS_STATUSES = frozenset({"OK", "SKIPPED_CACHED"})


@dataclass
class BackfillReport:
    start: date
    end: date
    calendar_days_scanned: int = 0
    holidays_skipped: int = 0
    successful_days: int = 0
    cached_days: int = 0
    quarantined_rows: int = 0
    rejected_files: int = 0
    failed_dates: list[date] = field(default_factory=list)
    skipped_dates: list[date] = field(default_factory=list)

    @property
    def unresolved_failed_dates(self) -> tuple[date, ...]:
        return tuple(self.failed_dates)

    def as_dict(self) -> dict[str, object]:
        return {
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "calendar_days_scanned": self.calendar_days_scanned,
            "holidays_skipped": self.holidays_skipped,
            "successful_days": self.successful_days,
            "cached_days": self.cached_days,
            "quarantined_rows": self.quarantined_rows,
            "rejected_files": self.rejected_files,
            "failed_dates": [day.isoformat() for day in self.failed_dates],
            "skipped_dates": [day.isoformat() for day in self.skipped_dates],
        }


def _calendar_days(
    engine: sa.Engine, start: date, end: date
) -> dict[date, tuple[bool, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT calendar_date, is_trading_day, session_type "
                "FROM trading_calendar WHERE calendar_date BETWEEN :start AND :end "
                "ORDER BY calendar_date"
            ),
            {"start": start, "end": end},
        ).all()
    if len(rows) != (end - start).days + 1:
        raise LookupError("trading calendar does not cover the complete backfill window")
    return {row[0]: (bool(row[1]), str(row[2])) for row in rows}


def _quarantine_count(engine: sa.Engine, target_date: date) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM ingest_quarantine q "
                    "JOIN ingest_runs r ON r.id = q.ingest_run_id "
                    "WHERE r.target_date = :target_date"
                ),
                {"target_date": target_date},
            ).scalar_one()
        )


def _wait_for_breaker() -> None:
    state = NSE_BREAKER.snapshot()
    remaining = float(state["cooldown_remaining_s"] or 0.0)
    if remaining > 0:
        log.warning("NSE breaker OPEN; waiting %.1fs before resuming backfill", remaining)
        time.sleep(remaining)


def _run_fetch(
    fetch: Callable[[], bytes],
    *,
    target_date: date,
) -> bytes:
    while True:
        try:
            return fetch()
        except CircuitOpenError:
            _wait_for_breaker()
            log.info("NSE breaker cooldown elapsed; retrying %s", target_date)


def run_backfill(
    start: date,
    end: date,
    *,
    engine: sa.Engine | None = None,
    cache_root: Path | None = None,
    from_cache_only: bool = False,
    inter_date_delay_s: float = 0.0,
    jitter_s: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> BackfillReport:
    """Ingest every trading date in ``[start, end]`` in dependency order."""
    if end < start:
        raise ValueError("--to must be on or after --from")
    engine = engine or get_engine()
    root = cache_root or get_settings().cache_root
    calendar = _calendar_days(engine, start, end)
    report = BackfillReport(start=start, end=end)

    for offset in range((end - start).days + 1):
        target_date = start + timedelta(days=offset)
        report.calendar_days_scanned += 1
        is_trading, session_type = calendar[target_date]
        if not is_trading:
            report.holidays_skipped += 1
            report.skipped_dates.append(target_date)
            continue

        try:
            bhavcopy = _run_fetch(
                partial(
                    _fetch_payload,
                    target_date,
                    from_cache_only=from_cache_only,
                    cache_root=root,
                ),
                target_date=target_date,
            )
            bhav_report = ingest_bhavcopy(
                bhavcopy,
                target_date,
                session_type=session_type,
                engine=engine,
                source_file=str(root / "bhavcopy" / target_date.isoformat()),
            )

            delivery_payload = _run_fetch(
                partial(
                    delivery.fetch_payload,
                    target_date,
                    from_cache_only=from_cache_only,
                    cache_root=root,
                ),
                target_date=target_date,
            )
            delivery_report = delivery.ingest_delivery(
                delivery_payload,
                target_date,
                engine=engine,
                cache_root=root,
                source_file=str(root / "delivery" / target_date.isoformat()),
            )

            index_payload = _run_fetch(
                partial(
                    index_data.fetch_payload,
                    target_date,
                    from_cache_only=from_cache_only,
                    cache_root=root,
                ),
                target_date=target_date,
            )
            index_report = index_data.ingest_index_eod(
                index_payload,
                target_date,
                engine=engine,
                source_file=str(root / "index_eod" / target_date.isoformat()),
            )
            capture_index_snapshot_0930(target_date, engine=engine)

            reports = (bhav_report, delivery_report, index_report)
            if any(item.status not in SUCCESS_STATUSES for item in reports):
                raise RuntimeError(
                    f"ingest status not successful for {target_date}: "
                    f"{[item.status for item in reports]}"
                )
            report.successful_days += 1
            if all(item.status == "SKIPPED_CACHED" for item in reports):
                report.cached_days += 1
            report.quarantined_rows += _quarantine_count(engine, target_date)
        except (NSEError, OSError, ValueError, RuntimeError) as exc:
            report.failed_dates.append(target_date)
            report.rejected_files += 1
            log.error("backfill failed for %s: %s", target_date, exc)
        if inter_date_delay_s or jitter_s:
            delay = max(0.0, inter_date_delay_s + random.uniform(-jitter_s, jitter_s))
            sleep(delay)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run chronological NSE backfill.")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    parser.add_argument("--from-cache-only", action="store_true")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--jitter", type=float, default=0.0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = run_backfill(
        args.start,
        args.end,
        from_cache_only=args.from_cache_only,
        inter_date_delay_s=args.delay,
        jitter_s=args.jitter,
    )
    print(report.as_dict())
    return 0 if not report.unresolved_failed_dates else 1


if __name__ == "__main__":
    raise SystemExit(main())
