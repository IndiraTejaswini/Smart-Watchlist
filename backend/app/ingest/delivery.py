"""Delivery data ingest pipeline -- ARCHITECTURE.md §6, §8.3, BUILD_PLAN task 2.2.

This module owns the ingestion of NSE's Security-wise deliverable positions file
(sec_bhavdata_full_{DDMMYYYY}.csv) into `delivery_stats`.

Key specifications and invariants:
  - Core Row Invariant: deliverable_qty <= traded_qty for 100% of committed rows.
    Any row violating this is rejected and routed to ingest_quarantine (reason:
    DELIV_GT_TRADED).
  - File-Level Stale/Holiday Check: Per Task 0.1 findings and docs/data-notes.md,
    on an exchange holiday the delivery endpoint serves HTTP 200 carrying the
    PREVIOUS trading day's data.  The loader extracts DATE1 before parsing rows.
    If DATE1 does not match the target session date, the entire payload is
    quarantined to data/cache/delivery_stale/{target_date}/ and exits with
    SKIPPED_HOLIDAY_STALE.  Zero rows are committed.
  - Transactional Integrity & Idempotency: Atomically upserts records within an
    engine.begin() block with SHA-256 caching in ingest_runs and
    ON CONFLICT (symbol, date) DO UPDATE.
  - Scope: NSE cash equities, EQ / BE / BZ series (§2.1).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.config import get_settings
from app.db import get_engine
from app.ingest import runs
from app.ingest.nse_client import (
    NSE_ARCHIVES,
    NSEClient,
    sha256_bytes,
    sidecar_path,
)
from app.timeutil import IST

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source & Cache configuration
# ---------------------------------------------------------------------------

DELIVERY_SOURCE = "delivery"
IN_SCOPE_SERIES = ("EQ", "BE", "BZ")

DELIVERY_URL = (
    NSE_ARCHIVES + "/products/content/sec_bhavdata_full_{date:%d%m%Y}.csv"
)
CACHE_DIR = "delivery"
STALE_CACHE_DIR = "delivery_stale"
CACHE_FILE_TEMPLATE = "sec_bhavdata_full_{date:%d%m%Y}.csv"
DATE1_FORMAT = "%d-%b-%Y"

# Rejection reason codes
DELIV_GT_TRADED = "DELIV_GT_TRADED"
TRADED_QTY_NEGATIVE = "TRADED_QTY_NEGATIVE"
DELIV_QTY_NEGATIVE = "DELIV_QTY_NEGATIVE"


class DeliveryError(ValueError):
    """The payload is not a readable delivery file."""


@dataclass(frozen=True)
class DeliveryRow:
    """Parsed delivery row for one symbol-date session."""

    symbol: str
    date: date
    series: str
    traded_qty: int
    deliverable_qty: int | None
    delivery_pct: Decimal | None


@dataclass
class IngestReport:
    """Summary of one delivery ingest run."""

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
                "delivery %s: SKIPPED_CACHED (run_id=%s)",
                self.target_date,
                self.run_id,
            )
            return
        if self.status == "SKIPPED_HOLIDAY_STALE":
            log.info(
                "delivery %s: SKIPPED_HOLIDAY_STALE -- %s (run_id=%s)",
                self.target_date,
                self.abort_reason,
                self.run_id,
            )
            return
        if self.abort_reason:
            log.warning(
                "delivery %s: FAILED -- %s (run_id=%s)",
                self.target_date,
                self.abort_reason,
                self.run_id,
            )
            return
        log.info(
            "delivery %s: %s -- committed=%d quarantined=%d (run_id=%s)",
            self.target_date,
            self.status,
            self.committed,
            self.quarantined,
            self.run_id,
        )


# ---------------------------------------------------------------------------
# Content-date extraction & Stale quarantine
# ---------------------------------------------------------------------------


def extract_content_date(payload: bytes) -> date | None:
    """Read the actual trading date (DATE1) from the first data row.

    On exchange holidays, NSE serves HTTP 200 with the previous session's rows.
    Validating DATE1 against the expected date detects this before any parsing.
    """
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = payload.decode("latin-1")
        except UnicodeDecodeError:
            return None

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
        first_row = next(reader)
    except StopIteration:
        return None

    try:
        col_map = {col.strip().upper(): idx for idx, col in enumerate(header)}
        date_col = col_map.get("DATE1")
        if date_col is None or date_col >= len(first_row):
            return None
        date_str = first_row[date_col].strip()
        return datetime.strptime(date_str, DATE1_FORMAT).date()
    except (ValueError, IndexError):
        return None


def quarantine_stale_payload(
    payload: bytes,
    target_date: date,
    cache_root: Path,
    filename: str | None = None,
) -> Path:
    """Quarantine a holiday/stale payload to data/cache/delivery_stale/{target_date}/.

    Preserves the file and its SHA-256 sidecar for auditability (§6.2).
    """
    dest_dir = cache_root / STALE_CACHE_DIR / target_date.isoformat()
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = filename or CACHE_FILE_TEMPLATE.format(date=target_date)
    file_path = dest_dir / fname
    file_path.write_bytes(payload)

    digest = sha256_bytes(payload)
    sidecar_path(file_path).write_text(f"{digest}  {fname}\n", encoding="ascii")
    log.warning(
        "quarantined stale delivery file for %s to %s",
        target_date,
        file_path,
    )
    return file_path


# ---------------------------------------------------------------------------
# Parsing & Validation
# ---------------------------------------------------------------------------


def _int(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if not text or text == "-":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _decimal(raw: str | None) -> Decimal | None:
    text = (raw or "").strip()
    if not text or text == "-":
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_delivery_rows(
    payload: bytes,
    target_date: date,
    *,
    series: Iterable[str] = IN_SCOPE_SERIES,
) -> list[DeliveryRow]:
    """Parse a delivery CSV into typed DeliveryRow records.

    Filters rows by `series` in `IN_SCOPE_SERIES` (EQ, BE, BZ).
    """
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise DeliveryError("delivery file has no header row")

    # Column names carry leading spaces in NSE delivery files (e.g. ' SERIES')
    reader.fieldnames = [name.strip().upper() for name in reader.fieldnames]

    wanted = set(series)
    rows: list[DeliveryRow] = []

    for row in reader:
        symbol = (row.get("SYMBOL") or "").strip()
        row_series = (row.get("SERIES") or "").strip()
        if not symbol or row_series not in wanted:
            continue

        traded_qty = _int(row.get("TTL_TRD_QNTY"))
        if traded_qty is None:
            continue

        deliverable_qty = _int(row.get("DELIV_QTY"))
        delivery_pct = _decimal(row.get("DELIV_PER"))

        rows.append(
            DeliveryRow(
                symbol=symbol,
                date=target_date,
                series=row_series,
                traded_qty=traded_qty,
                deliverable_qty=deliverable_qty,
                delivery_pct=delivery_pct,
            )
        )

    return rows


def validate_delivery_row(row: DeliveryRow) -> list[str]:
    """Validate row invariants.

    Core Invariant:
      deliverable_qty <= traded_qty for 100% of committed rows.
      Violation reason: DELIV_GT_TRADED.
    """
    reasons: list[str] = []

    if row.traded_qty < 0:
        reasons.append(TRADED_QTY_NEGATIVE)

    if row.deliverable_qty is not None:
        if row.deliverable_qty < 0:
            reasons.append(DELIV_QTY_NEGATIVE)
        elif row.deliverable_qty > row.traded_qty:
            reasons.append(DELIV_GT_TRADED)

    return reasons


def _row_to_jsonb(row: DeliveryRow, reasons: list[str]) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "date": row.date.isoformat(),
        "series": row.series,
        "traded_qty": row.traded_qty,
        "deliverable_qty": row.deliverable_qty,
        "delivery_pct": str(row.delivery_pct) if row.delivery_pct is not None else None,
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
    rejected: list[tuple[DeliveryRow, list[str]]],
) -> None:
    conn.execute(
        _INSERT_QUARANTINE,
        [
            {
                "run_id": run_id,
                "source_file": source_file,
                "payload": json.dumps(_row_to_jsonb(row, reasons)),
                "reason": ",".join(reasons),
            }
            for row, reasons in rejected
        ],
    )


# ---------------------------------------------------------------------------
# Database Upsert
# ---------------------------------------------------------------------------

_UPSERT_DELIVERY = sa.text(
    "INSERT INTO delivery_stats"
    " (symbol, date, traded_qty, deliverable_qty, delivery_pct, series, source, ingested_at)"
    " VALUES"
    " (:symbol, :date, :traded_qty, :deliverable_qty, :delivery_pct,"
    "  :series, :source, :ingested_at)"
    " ON CONFLICT (symbol, date) DO UPDATE SET"
    "   traded_qty      = EXCLUDED.traded_qty,"
    "   deliverable_qty = EXCLUDED.deliverable_qty,"
    "   delivery_pct    = EXCLUDED.delivery_pct,"
    "   series          = EXCLUDED.series,"
    "   source          = EXCLUDED.source,"
    "   ingested_at     = EXCLUDED.ingested_at"
)


def _delivery_to_params(row: DeliveryRow, ingested_at: datetime) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "date": row.date,
        "traded_qty": row.traded_qty,
        "deliverable_qty": row.deliverable_qty,
        "delivery_pct": row.delivery_pct,
        "series": row.series,
        "source": DELIVERY_SOURCE,
        "ingested_at": ingested_at,
    }


# ---------------------------------------------------------------------------
# Ingest Orchestrator
# ---------------------------------------------------------------------------


def ingest_delivery(
    payload: bytes,
    target_date: date,
    *,
    source_file: str = "",
    engine: sa.Engine | None = None,
    cache_root: Path | None = None,
    dry_run: bool = False,
) -> IngestReport:
    """Ingest a Security-wise delivery file for `target_date`.

    Parameters
    ----------
    payload:
        Raw bytes of the CSV file.
    target_date:
        Expected IST trading date.
    source_file:
        File label/path for quarantine records.
    engine:
        SQLAlchemy engine. Defaults to `get_engine()`.
    cache_root:
        Cache directory root for quarantine. Defaults to settings.
    dry_run:
        Parse and validate without committing to the database.

    Returns
    -------
    IngestReport
    """
    report = IngestReport(target_date=target_date)
    engine = engine or get_engine()
    root = cache_root or get_settings().cache_root

    # §6.2 rule 3: SHA-256 before parsing
    file_hash = sha256_bytes(payload)

    with engine.begin() as conn:
        # Check cache hit
        if runs.already_ingested(
            conn, source=DELIVERY_SOURCE, target_date=target_date, file_hash=file_hash
        ):
            run_id = runs.start_run(
                conn, source=DELIVERY_SOURCE, target_date=target_date, file_hash=file_hash
            )
            runs.finish_run(conn, run_id, status="SKIPPED_CACHED", rows=0)
            report.run_id = run_id
            report.status = "SKIPPED_CACHED"
            report.skipped_cached = True
            report.log()
            return report

        # Open run row
        run_id = runs.start_run(
            conn, source=DELIVERY_SOURCE, target_date=target_date, file_hash=file_hash
        )
        report.run_id = run_id

        # File-Level Stale/Holiday Check: validate DATE1
        content_date = extract_content_date(payload)
        if content_date is not None and content_date != target_date:
            abort_msg = (
                f"DATE1 {content_date.isoformat()} does not match target date "
                f"{target_date.isoformat()} (stale holiday HTTP 200 payload)"
            )
            quarantine_stale_payload(payload, target_date, root)
            runs.finish_run(
                conn,
                run_id,
                status="SKIPPED_HOLIDAY_STALE",
                rows=0,
                error=abort_msg,
            )
            report.status = "SKIPPED_HOLIDAY_STALE"
            report.abort_reason = abort_msg
            report.log()
            return report

        # Parse rows
        try:
            rows = parse_delivery_rows(payload, target_date)
        except DeliveryError as exc:
            runs.finish_run(conn, run_id, status="FAILED", rows=0, error=str(exc))
            report.status = "FAILED"
            report.abort_reason = str(exc)
            report.log()
            raise

        if dry_run:
            runs.finish_run(conn, run_id, status="OK", rows=len(rows))
            report.committed = len(rows)
            report.status = "OK"
            log.info("delivery %s: --dry-run, %d rows parsed", target_date, len(rows))
            return report

        # Validate rows
        good: list[DeliveryRow] = []
        rejected: list[tuple[DeliveryRow, list[str]]] = []
        for r in rows:
            reasons = validate_delivery_row(r)
            if reasons:
                rejected.append((r, reasons))
            else:
                good.append(r)

        # Quarantined rows
        if rejected:
            _write_quarantine_rows(conn, run_id, source_file, rejected)

        # Upsert clean rows
        ingested_at = datetime.now(tz=IST)
        if good:
            conn.execute(
                _UPSERT_DELIVERY,
                [_delivery_to_params(r, ingested_at) for r in good],
            )

        committed = len(good)
        quarantined_count = len(rejected)

        runs.finish_run(conn, run_id, status="OK", rows=committed)
        report.committed = committed
        report.quarantined = quarantined_count
        report.status = "OK"

    report.log()
    return report


# ---------------------------------------------------------------------------
# Fetch from NSE Cache
# ---------------------------------------------------------------------------


def fetch_payload(
    target_date: date,
    *,
    from_cache_only: bool = False,
    cache_root: Path | None = None,
) -> bytes:
    """Download or read from cache the Security-wise delivery file."""
    root = cache_root or get_settings().cache_root
    filename = CACHE_FILE_TEMPLATE.format(date=target_date)
    with NSEClient(from_cache_only=from_cache_only, cache_root=root) as client:
        payload = client.fetch(
            DELIVERY_URL.format(date=target_date),
            source=CACHE_DIR,
            target_date=target_date,
            filename=filename,
        )
    if payload is None:
        raise DeliveryError(f"no delivery data available for {target_date}")
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest NSE Security-wise delivery positions file (§6, §8.3)."
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        required=True,
        help="IST trading date, e.g. 2026-09-04",
    )
    parser.add_argument("--from-cache-only", action="store_true")
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without committing.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )

    try:
        payload = fetch_payload(
            args.date,
            from_cache_only=args.from_cache_only,
            cache_root=args.cache_root,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("fetch failed for %s: %s", args.date, exc)
        return 1

    cache_label = str(args.cache_root or get_settings().cache_root)
    source_file = (
        f"{cache_label}/{CACHE_DIR}/{args.date}/"
        f"{CACHE_FILE_TEMPLATE.format(date=args.date)}"
    )

    try:
        report = ingest_delivery(
            payload,
            args.date,
            source_file=source_file,
            cache_root=args.cache_root,
            dry_run=args.dry_run,
        )
        if report.status in ("OK", "SKIPPED_CACHED", "SKIPPED_HOLIDAY_STALE"):
            return 0
        return 1
    except Exception as exc:  # noqa: BLE001
        log.error("ingest failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
