"""Bhavcopy ingest orchestrator -- docs/BUILD_SPEC.md §6.2, BUILD_PLAN task 2.1.

This module owns the full §6.2 ingest contract for the UDiFF bhavcopy.
The parser (bhavcopy.py) converts bytes to typed Bar objects and is unchanged.
This module wraps those bars in every database obligation:

  §6.2 rule 1 -- Idempotent upsert on (symbol, date) PK.
  §6.2 rule 2 -- Writes an ingest_runs row; opens FAILED, closes OK or SKIPPED.
  §6.2 rule 3 -- SHA-256 content hash before parsing; exits SKIPPED_CACHED on match.
  §6.2 rule 4 -- Row validation; invalid bars quarantined, never committed.
  §6.2 rule 5 -- Quarantine with rejection_reason; rows never silently dropped.
  §6.2 rule 6 -- Two-sided count check (floor + rolling-median deviation).
  §6.2 rule 7 -- One transaction per file; no partial commits.

The two-sided count check is suppressed when session_type is MUHURAT or
HALF_DAY, because volumes are legitimately abnormal on those days (§6.1 / §6.2).

Design: same parser/orchestrator split as ca_parser.py vs ca_verify.py.
bhavcopy.py is imported by ca_verify with no DB dependency; pulling DB logic
into it would break that clean path.

Usage::

    python -m app.ingest.bhavcopy_ingest --date 2026-09-04
    python -m app.ingest.bhavcopy_ingest --date 2026-09-04 --from-cache-only
    python -m app.ingest.bhavcopy_ingest --date 2026-09-04 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.constants import (
    ACTIVE_ROW_FLOOR_FRAC,
    BHAVCOPY_ROW_COUNT_MEDIAN_WINDOW,
    QUARANTINE_ABORT_FRAC,
    ROW_COUNT_DEVIATION,
)
from app.db import get_engine
from app.ingest import runs
from app.ingest.bhavcopy import BHAVCOPY_SOURCE, Bar, BhavcopyError, read_bhavcopy
from app.ingest.nse_client import NSEClient, sha256_bytes
from app.timeutil import IST

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source / cache config -- addresses are not business thresholds (same
# convention as symbol_master.py and corporate_actions.py).
# ---------------------------------------------------------------------------
SOURCE = BHAVCOPY_SOURCE

NSE_ARCHIVES = "https://nsearchives.nseindia.com"
# Primary UDiFF format: zipped CSV.  Tried first; plain CSV is the fallback.
BHAVCOPY_ZIP_URL = (
    NSE_ARCHIVES
    + "/content/cm/BhavCopy_NSE_CM_0_0_0_{date:%Y%m%d}_F_0000.csv.zip"
)
BHAVCOPY_CSV_URL = (
    NSE_ARCHIVES
    + "/products/content/sec_bhavdata_full_{date:%d%m%Y}.csv"
)
CACHE_DIR = "bhavcopy"
# Must match the real NSE archive filename — it is what scripts/backfill.py
# (Task 0.1) actually writes to disk, and the two must agree on the same
# cache convention or --from-cache-only can never find what was downloaded.
CACHE_FILE = "BhavCopy_NSE_CM_0_0_0_{date:%Y%m%d}_F_0000.csv.zip"

# Window for the rolling median row-count check — R1: sourced from the registry.
MEDIAN_WINDOW = BHAVCOPY_ROW_COUNT_MEDIAN_WINDOW

# Session types that suppress the two-sided count check (§6.2 note, §6.1).
_SUPPRESS_COUNT_CHECK: frozenset[str] = frozenset({"MUHURAT", "HALF_DAY"})

# ---------------------------------------------------------------------------
# Rejection reason codes written to ingest_quarantine.rejection_reason.
# These codes are stable strings that callers (tests, ops dashboards) match on.
# ---------------------------------------------------------------------------
HIGH_LT_LOW = "HIGH_LT_LOW"
HIGH_LT_OPEN_CLOSE = "HIGH_LT_OPEN_CLOSE"
LOW_GT_OPEN_CLOSE = "LOW_GT_OPEN_CLOSE"
VOLUME_NEGATIVE = "VOLUME_NEGATIVE"


# ---------------------------------------------------------------------------
# Validation -- §6.2 rule 4
# ---------------------------------------------------------------------------


def validate_bar(bar: Bar) -> list[str]:
    """Return rejection reason codes for a parsed Bar.

    Returns an empty list when the bar is clean.  Only checks relationships
    between non-None fields: a None field is permitted (thinly-traded days can
    have partial data; the DB enforces NOT NULL separately).

    Rules are verbatim from §6.2 rule 4:
        high >= low
        high >= max(open, close)
        low  <= min(open, close)
        volume >= 0
    """
    reasons: list[str] = []

    h, lo, o, c, v = bar.high, bar.low, bar.open, bar.close, bar.volume

    if h is not None and lo is not None and h < lo:
        reasons.append(HIGH_LT_LOW)

    if h is not None:
        candidates: list[Decimal] = []
        if o is not None:
            candidates.append(o)
        if c is not None:
            candidates.append(c)
        if candidates and h < max(candidates):
            reasons.append(HIGH_LT_OPEN_CLOSE)

    if lo is not None:
        candidates2: list[Decimal] = []
        if o is not None:
            candidates2.append(o)
        if c is not None:
            candidates2.append(c)
        if candidates2 and lo > min(candidates2):
            reasons.append(LOW_GT_OPEN_CLOSE)

    if v is not None and v < 0:
        reasons.append(VOLUME_NEGATIVE)

    return reasons


# ---------------------------------------------------------------------------
# Quarantine -- §6.2 rule 5
# ---------------------------------------------------------------------------


def _bar_to_jsonb(bar: Bar, reasons: list[str]) -> dict[str, Any]:
    """Serialise a Bar to a JSONB-safe dict for ingest_quarantine.raw_payload."""
    return {
        "symbol": bar.symbol,
        "date": bar.date.isoformat(),
        "series": bar.series,
        "open": str(bar.open) if bar.open is not None else None,
        "high": str(bar.high) if bar.high is not None else None,
        "low": str(bar.low) if bar.low is not None else None,
        "close": str(bar.close) if bar.close is not None else None,
        "prev_close": str(bar.prev_close) if bar.prev_close is not None else None,
        "last": str(bar.last) if bar.last is not None else None,
        "volume": bar.volume,
        "turnover": str(bar.turnover) if bar.turnover is not None else None,
        "trades": bar.trades,
        "_reasons": reasons,
    }


_INSERT_QUARANTINE = sa.text(
    "INSERT INTO ingest_quarantine"
    " (ingest_run_id, source_file, raw_payload, rejection_reason)"
    " VALUES (:run_id, :source_file, cast(:payload as jsonb), :reason)"
)


def _write_quarantine_rows(
    conn: sa.Connection,
    run_id: int,
    source_file: str,
    rejected: list[tuple[Bar, list[str]]],
) -> None:
    """Bulk-insert all rejected bars into ingest_quarantine.

    Multiple reasons on one bar produce a single quarantine row whose
    rejection_reason is the comma-joined list.  All information is preserved
    while matching the column's scalar cardinality.
    """
    conn.execute(
        _INSERT_QUARANTINE,
        [
            {
                "run_id": run_id,
                "source_file": source_file,
                "payload": json.dumps(_bar_to_jsonb(bar, reasons)),
                "reason": ",".join(reasons),
            }
            for bar, reasons in rejected
        ],
    )


# ---------------------------------------------------------------------------
# Count checks -- §6.2 rule 6
# ---------------------------------------------------------------------------


def _active_instrument_count(conn: sa.Connection) -> int:
    """Count of is_active instruments -- the floor denominator in §6.2 rule 6."""
    return int(
        conn.execute(
            sa.text("SELECT COUNT(*) FROM instruments WHERE is_active")
        ).scalar_one()
    )


def _rolling_median_row_count(conn: sa.Connection) -> float | None:
    """Median row count over the last MEDIAN_WINDOW successful bhavcopy runs.

    Returns None when fewer than 2 prior successful runs exist, in which case
    the median check is skipped.  Skipping on the first few runs avoids false
    aborts during initial backfill -- there is no meaningful baseline yet.

    Why 2 as the minimum (not MEDIAN_WINDOW): with a single prior run the median
    equals that run's count exactly, making the deviation check degenerate (it
    always passes unless the new count differs by more than ROW_COUNT_DEVIATION
    from itself, which can never happen).  Two samples give a genuine average.
    MEDIAN_WINDOW is the window ceiling, not the minimum.
    """
    row_counts: list[int] = [
        int(r)
        for r in conn.execute(
            sa.text(
                "SELECT rows FROM ingest_runs"
                " WHERE source = :source AND status = 'OK' AND rows IS NOT NULL"
                " ORDER BY finished_at DESC NULLS LAST"
                f" LIMIT {MEDIAN_WINDOW}"
            ),
            {"source": SOURCE},
        )
        .scalars()
        .all()
    ]
    if len(row_counts) < 2:  # noqa: PLR2004
        return None
    return statistics.median(row_counts)


# ---------------------------------------------------------------------------
# DB upsert -- §6.2 rule 1
# ---------------------------------------------------------------------------

_UPSERT_BAR = sa.text(
    "INSERT INTO daily_bars"
    " (symbol, date, open, high, low, close, prev_close, volume,"
    "  turnover, trades, series, source, ingested_at)"
    " VALUES"
    " (:symbol, :date, :open, :high, :low, :close, :prev_close, :volume,"
    "  :turnover, :trades, :series, :source, :ingested_at)"
    " ON CONFLICT (symbol, date) DO UPDATE SET"
    "   open        = EXCLUDED.open,"
    "   high        = EXCLUDED.high,"
    "   low         = EXCLUDED.low,"
    "   close       = EXCLUDED.close,"
    "   prev_close  = EXCLUDED.prev_close,"
    "   volume      = EXCLUDED.volume,"
    "   turnover    = EXCLUDED.turnover,"
    "   trades      = EXCLUDED.trades,"
    "   series      = EXCLUDED.series,"
    "   source      = EXCLUDED.source,"
    "   ingested_at = EXCLUDED.ingested_at"
)


def _bar_to_row(bar: Bar, ingested_at: datetime) -> dict[str, Any]:
    return {
        "symbol": bar.symbol,
        "date": bar.date,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "prev_close": bar.prev_close,
        "volume": bar.volume,
        "turnover": bar.turnover,
        "trades": bar.trades,
        "series": bar.series,
        "source": SOURCE,
        "ingested_at": ingested_at,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class IngestReport:
    """Summary of one bhavcopy ingest run."""

    target_date: date
    run_id: int | None = None
    status: str = "FAILED"
    committed: int = 0
    quarantined: int = 0
    skipped_cached: bool = False
    abort_reason: str | None = None

    def log(self) -> None:
        if self.skipped_cached:
            log.info(
                "bhavcopy %s: SKIPPED_CACHED (run_id=%s)",
                self.target_date,
                self.run_id,
            )
            return
        if self.abort_reason:
            log.warning(
                "bhavcopy %s: FAILED -- %s (run_id=%s)",
                self.target_date,
                self.abort_reason,
                self.run_id,
            )
            return
        log.info(
            "bhavcopy %s: %s -- committed=%d quarantined=%d (run_id=%s)",
            self.target_date,
            self.status,
            self.committed,
            self.quarantined,
            self.run_id,
        )


class BhavcopyAbortError(RuntimeError):
    """Count check or quarantine ratio tripped; no daily_bars rows committed."""


# ---------------------------------------------------------------------------
# Fetch -- wraps the NSE client cache layer
# ---------------------------------------------------------------------------


def _fetch_payload(
    target_date: date,
    *,
    from_cache_only: bool = False,
    cache_root: Path | None = None,
) -> bytes:
    """Download (or read from cache) the bhavcopy for ``target_date``.

    The NSE client handles retries, backoff, the circuit breaker, and the
    on-disk SHA-256 sidecar cache.  This function selects the URL and namespace.
    """
    root = cache_root or Path("data/cache")
    filename = CACHE_FILE.format(date=target_date)
    with NSEClient(from_cache_only=from_cache_only, cache_root=root) as client:
        payload = client.fetch(
            BHAVCOPY_ZIP_URL.format(date=target_date),
            source=CACHE_DIR,
            target_date=target_date,
            filename=filename,
            accept_missing=True,
        )
        if payload is None:
            csv_filename = f"sec_bhavdata_full_{target_date:%d%m%Y}.csv"
            payload = client.fetch(
                BHAVCOPY_CSV_URL.format(date=target_date),
                source=CACHE_DIR,
                target_date=target_date,
                filename=csv_filename,
            )
    if payload is None:
        raise BhavcopyError(f"no bhavcopy available for {target_date}")
    return payload


# ---------------------------------------------------------------------------
# Core ingest -- §6.2 rules 1-7
# ---------------------------------------------------------------------------


def ingest_bhavcopy(
    payload: bytes,
    target_date: date,
    *,
    session_type: str = "REGULAR",
    source_file: str = "",
    engine: sa.Engine | None = None,
    dry_run: bool = False,
) -> IngestReport:
    """Ingest a raw bhavcopy payload (zipped or plain CSV) for ``target_date``.

    Parameters
    ----------
    payload:
        Raw bytes as downloaded from NSE (zip or plain CSV).
    target_date:
        The IST trading date this bhavcopy covers.
    session_type:
        ``trading_calendar.session_type`` for this date.  MUHURAT and HALF_DAY
        suppress the two-sided count check (§6.2 / §6.1).
    source_file:
        Human-readable label written into quarantine rows (e.g. the cache path).
    engine:
        SQLAlchemy engine.  Defaults to ``get_engine()``.
    dry_run:
        Parse and validate but write nothing to the database.

    Returns
    -------
    IngestReport
        Final counts and status.

    Raises
    ------
    BhavcopyAbortError
        When the quarantine ratio or a count check trips.  The transaction is
        rolled back; no ``daily_bars`` rows are committed.
    BhavcopyError
        When the payload cannot be parsed at all.
    """
    report = IngestReport(target_date=target_date)
    engine = engine or get_engine()

    # §6.2 rule 3: hash before parsing.
    file_hash = sha256_bytes(payload)

    with engine.begin() as conn:
        # -- §6.2 rule 3: skip if already ingested -------------------------
        if runs.already_ingested(
            conn, source=SOURCE, target_date=target_date, file_hash=file_hash
        ):
            run_id = runs.start_run(
                conn, source=SOURCE, target_date=target_date, file_hash=file_hash
            )
            runs.finish_run(conn, run_id, status="SKIPPED_CACHED", rows=0)
            report.run_id = run_id
            report.status = "SKIPPED_CACHED"
            report.skipped_cached = True
            report.log()
            return report

        # -- §6.2 rule 2: open run row (FAILED until proven otherwise) ------
        run_id = runs.start_run(
            conn, source=SOURCE, target_date=target_date, file_hash=file_hash
        )
        report.run_id = run_id

        # -- dry-run path ---------------------------------------------------
        if dry_run:
            bars = read_bhavcopy(payload)
            n = len(bars)
            runs.finish_run(conn, run_id, status="OK", rows=n)
            report.committed = n
            report.status = "OK"
            log.info(
                "bhavcopy %s: --dry-run, %d rows parsed, nothing written",
                target_date,
                n,
            )
            return report

        # -- §6.2 rule 4/5: parse then validate ----------------------------
        try:
            bars = read_bhavcopy(payload)
        except BhavcopyError as exc:
            runs.finish_run(conn, run_id, status="FAILED", rows=0, error=str(exc))
            raise

        good: list[Bar] = []
        rejected: list[tuple[Bar, list[str]]] = []
        for bar in bars:
            reasons = validate_bar(bar)
            if reasons:
                rejected.append((bar, reasons))
            else:
                good.append(bar)

        total = len(bars)
        quarantined_count = len(rejected)

        # Write quarantine rows *before* the abort check so bad rows are
        # never silently discarded even when we roll back daily_bars.
        if rejected:
            _write_quarantine_rows(conn, run_id, source_file, rejected)

        abort_msg: str | None = None

        # -- §6.2 rule 6a: quarantine-ratio abort --------------------------
        if total > 0 and quarantined_count / total > QUARANTINE_ABORT_FRAC:
            abort_msg = (
                f"quarantine ratio {quarantined_count}/{total}"
                f" = {quarantined_count / total:.1%}"
                f" exceeds QUARANTINE_ABORT_FRAC ({QUARANTINE_ABORT_FRAC:.0%})"
            )

        committed = len(good)

        # -- §6.2 rule 6b: two-sided count check (suppressed on short sessions)
        if abort_msg is None and session_type not in _SUPPRESS_COUNT_CHECK:
            active_count = _active_instrument_count(conn)
            if active_count > 0:
                floor = int(ACTIVE_ROW_FLOOR_FRAC * active_count)
                if committed < floor:
                    abort_msg = (
                        f"committed rows {committed} < active-symbol floor {floor}"
                        f" ({ACTIVE_ROW_FLOOR_FRAC:.0%} of {active_count}"
                        " active instruments)"
                    )

            if abort_msg is None:
                median = _rolling_median_row_count(conn)
                if median is not None and median > 0:
                    deviation = abs(committed - median) / median
                    if deviation > ROW_COUNT_DEVIATION:
                        abort_msg = (
                            f"committed rows {committed} deviates {deviation:.1%}"
                            f" from {MEDIAN_WINDOW}-run median {median:.0f}"
                            f" (ROW_COUNT_DEVIATION={ROW_COUNT_DEVIATION:.0%})"
                        )

        if abort_msg is not None:
            # Abort: quarantine rows are saved and ingest_runs is marked FAILED,
            # but daily_bars is never touched (never partially commits).
            runs.finish_run(conn, run_id, status="FAILED", rows=total, error=abort_msg)
            report.quarantined = quarantined_count
            report.abort_reason = abort_msg
            report.status = "FAILED"
            report.log()
        else:
            # -- §6.2 rules 1 + 7: idempotent upsert, one transaction ----------
            ingested_at = datetime.now(tz=IST)
            if good:
                conn.execute(_UPSERT_BAR, [_bar_to_row(bar, ingested_at) for bar in good])

            runs.finish_run(conn, run_id, status="OK", rows=committed)
            report.committed = committed
            report.quarantined = quarantined_count
            report.status = "OK"
            report.log()

    if report.abort_reason is not None:
        raise BhavcopyAbortError(report.abort_reason)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest a UDiFF bhavcopy for one trading date (§6.2)."
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        required=True,
        help="IST trading date, e.g. 2026-09-04",
    )
    parser.add_argument(
        "--session-type",
        default="REGULAR",
        choices=["REGULAR", "MUHURAT", "HALF_DAY", "CLOSED"],
        help="Calendar session type (MUHURAT/HALF_DAY suppress count checks)",
    )
    parser.add_argument("--from-cache-only", action="store_true")
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate, write nothing to the database.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )

    try:
        payload = _fetch_payload(
            args.date,
            from_cache_only=args.from_cache_only,
            cache_root=args.cache_root,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("fetch failed for %s: %s", args.date, exc)
        return 1

    cache_label = str(args.cache_root or "data/cache")
    try:
        ingest_bhavcopy(
            payload,
            args.date,
            session_type=args.session_type,
            source_file=f"{cache_label}/bhavcopy/{args.date}.zip",
            dry_run=args.dry_run,
        )
    except BhavcopyAbortError as exc:
        log.error("ingest aborted: %s", exc)
        return 1
    except BhavcopyError as exc:
        log.error("parse error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
