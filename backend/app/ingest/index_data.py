"""Index EOD ingest pipeline -- ARCHITECTURE.md §6, BUILD_PLAN task 2.3.

This module ingests NSE index daily closing data (ind_close_all_DDMMYYYY.csv)
into `index_bars`.

Key specifications and invariants:
  - Target Schema Alignment: Ingests into `index_bars` with PK `(index_symbol, date)`
    matching 001_full_schema.py.
  - Robust CSV Parsing: Parses `ind_close_all_{DDMMYYYY}.csv`, cleans formatting
    (strips thousands commas, coerces "-" markers to None), computes or extracts
    prev_close where available.
  - Invariant & Bounds Validation:
      high >= low
      high >= max(open, close)
      low <= min(open, close)
      row date == target trading date
    Malformed rows are routed to `ingest_quarantine` with reasons:
    `INDEX_HIGH_LT_LOW`, `INDEX_HIGH_LT_OPEN_CLOSE`, `INDEX_LOW_GT_OPEN_CLOSE`,
    `INDEX_DATE_MISMATCH`.
  - No Speculative Semantics (Rule R1/R3): Ingests canonical index names cleanly
    as published ('Nifty 50', 'Nifty Next 50', 'Nifty Total Market', etc.).
  - Idempotent & Transactional: Single engine.begin() transaction with SHA-256
    caching (SKIPPED_CACHED) and ON CONFLICT (index_symbol, date) DO UPDATE.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
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
)
from app.timeutil import IST

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDEX_SOURCE = "index_eod"

INDEX_EOD_URL = (
    NSE_ARCHIVES + "/content/indices/ind_close_all_{date:%d%m%Y}.csv"
)
CACHE_DIR = "index_eod"
CACHE_FILE_TEMPLATE = "ind_close_all_{date:%d%m%Y}.csv"

DATE_FORMATS = ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y")

# Rejection reason codes
INDEX_HIGH_LT_LOW = "INDEX_HIGH_LT_LOW"
INDEX_HIGH_LT_OPEN_CLOSE = "INDEX_HIGH_LT_OPEN_CLOSE"
INDEX_LOW_GT_OPEN_CLOSE = "INDEX_LOW_GT_OPEN_CLOSE"
INDEX_DATE_MISMATCH = "INDEX_DATE_MISMATCH"


class IndexEodError(ValueError):
    """The payload is not a readable index EOD file."""


@dataclass(frozen=True)
class IndexEodRow:
    """Parsed index EOD session row."""

    index_name: str
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    prev_close: Decimal | None = None
    volume: int | None = None
    turnover: Decimal | None = None


@dataclass
class IngestReport:
    """Summary of one index EOD ingest run."""

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
                "index_eod %s: SKIPPED_CACHED (run_id=%s)",
                self.target_date,
                self.run_id,
            )
            return
        if self.abort_reason:
            log.warning(
                "index_eod %s: FAILED -- %s (run_id=%s)",
                self.target_date,
                self.abort_reason,
                self.run_id,
            )
            return
        log.info(
            "index_eod %s: %s -- committed=%d quarantined=%d (run_id=%s)",
            self.target_date,
            self.status,
            self.committed,
            self.quarantined,
            self.run_id,
        )


# ---------------------------------------------------------------------------
# Numeric & Date Cleanse Helpers
# ---------------------------------------------------------------------------


def _clean_decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text or text == "-" or text.upper() in ("N/A", "NULL"):
        return None
    cleaned = text.replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _clean_int(raw: str | None) -> int | None:
    d = _clean_decimal(raw)
    return int(d) if d is not None else None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    text = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# CSV Parsing & Row Validation
# ---------------------------------------------------------------------------


def _norm_col(col: str) -> str:
    return "".join(c.lower() for c in col if c.isalnum())


def parse_index_eod_rows(payload: bytes, target_date: date) -> list[IndexEodRow]:
    """Parse raw bytes of ind_close_all_DDMMYYYY.csv into IndexEodRow records."""
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("latin-1")

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise IndexEodError("index EOD file is empty") from None

    # Map normalized column names to column indexes
    col_map: dict[str, int] = {}
    for idx, col in enumerate(header):
        normalized = _norm_col(col)
        col_map[normalized] = idx

    def get_val(row_vals: list[str], *aliases: str) -> str | None:
        for alias in aliases:
            norm = _norm_col(alias)
            if norm in col_map and col_map[norm] < len(row_vals):
                val = row_vals[col_map[norm]].strip()
                if val:
                    return val
        return None

    rows: list[IndexEodRow] = []

    for row_vals in reader:
        if not row_vals or not any(v.strip() for v in row_vals):
            continue

        name = get_val(row_vals, "Index Name", "Index_Name", "Symbol", "Index")
        if not name:
            continue

        date_str = get_val(row_vals, "Index Date", "Date", "Index_Date", "TradDt")
        row_date = _parse_date(date_str) or target_date

        open_val = _clean_decimal(get_val(row_vals, "Open Index Value", "Open"))
        high_val = _clean_decimal(get_val(row_vals, "High Index Value", "High"))
        low_val = _clean_decimal(get_val(row_vals, "Low Index Value", "Low"))
        close_val = _clean_decimal(get_val(row_vals, "Closing Index Value", "Close"))

        # Previous close: either directly reported or computed via Points Change
        prev_close_val = _clean_decimal(get_val(row_vals, "Previous Close", "Prev_Close"))
        if prev_close_val is None and close_val is not None:
            pts_change = _clean_decimal(get_val(row_vals, "Points Change", "Change"))
            if pts_change is not None:
                prev_close_val = close_val - pts_change

        volume_val = _clean_int(get_val(row_vals, "Volume", "Total Trading Volume"))
        turnover_val = _clean_decimal(get_val(row_vals, "Turnover (Rs. Cr.)", "Turnover"))

        rows.append(
            IndexEodRow(
                index_name=name,
                date=row_date,
                open=open_val,
                high=high_val,
                low=low_val,
                close=close_val,
                prev_close=prev_close_val,
                volume=volume_val,
                turnover=turnover_val,
            )
        )

    return rows


def validate_index_row(row: IndexEodRow, target_date: date) -> list[str]:
    """Validate bounds and session date invariants.

    Invariants:
      - row.date == target_date (rejection: INDEX_DATE_MISMATCH)
      - high >= low (rejection: INDEX_HIGH_LT_LOW)
      - high >= max(open, close) (rejection: INDEX_HIGH_LT_OPEN_CLOSE)
      - low <= min(open, close) (rejection: INDEX_LOW_GT_OPEN_CLOSE)
    """
    reasons: list[str] = []

    if row.date != target_date:
        reasons.append(INDEX_DATE_MISMATCH)

    h, lo, o, c = row.high, row.low, row.open, row.close

    if h is not None and lo is not None and h < lo:
        reasons.append(INDEX_HIGH_LT_LOW)

    if h is not None:
        needed_hi: list[Decimal] = []
        if o is not None:
            needed_hi.append(o)
        if c is not None:
            needed_hi.append(c)
        if needed_hi and h < max(needed_hi):
            reasons.append(INDEX_HIGH_LT_OPEN_CLOSE)

    if lo is not None:
        needed_lo: list[Decimal] = []
        if o is not None:
            needed_lo.append(o)
        if c is not None:
            needed_lo.append(c)
        if needed_lo and lo > min(needed_lo):
            reasons.append(INDEX_LOW_GT_OPEN_CLOSE)

    return reasons


# ---------------------------------------------------------------------------
# Database Quarantine & Upsert
# ---------------------------------------------------------------------------


def _index_row_to_jsonb(row: IndexEodRow, reasons: list[str]) -> dict[str, Any]:
    return {
        "index_name": row.index_name,
        "date": row.date.isoformat(),
        "open": str(row.open) if row.open is not None else None,
        "high": str(row.high) if row.high is not None else None,
        "low": str(row.low) if row.low is not None else None,
        "close": str(row.close) if row.close is not None else None,
        "prev_close": str(row.prev_close) if row.prev_close is not None else None,
        "volume": row.volume,
        "turnover": str(row.turnover) if row.turnover is not None else None,
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
    rejected: list[tuple[IndexEodRow, list[str]]],
) -> None:
    conn.execute(
        _INSERT_QUARANTINE,
        [
            {
                "run_id": run_id,
                "source_file": source_file,
                "payload": json.dumps(_index_row_to_jsonb(row, reasons)),
                "reason": ",".join(reasons),
            }
            for row, reasons in rejected
        ],
    )


_UPSERT_INDEX_BAR = sa.text(
    "INSERT INTO index_bars"
    " (index_symbol, date, open, high, low, close, prev_close, source, ingested_at)"
    " VALUES"
    " (:index_symbol, :date, :open, :high, :low, :close, :prev_close, :source, :ingested_at)"
    " ON CONFLICT (index_symbol, date) DO UPDATE SET"
    "   open        = EXCLUDED.open,"
    "   high        = EXCLUDED.high,"
    "   low         = EXCLUDED.low,"
    "   close       = EXCLUDED.close,"
    "   prev_close  = EXCLUDED.prev_close,"
    "   source      = EXCLUDED.source,"
    "   ingested_at = EXCLUDED.ingested_at"
)


def _index_to_params(row: IndexEodRow, ingested_at: datetime) -> dict[str, Any]:
    return {
        "index_symbol": row.index_name,
        "date": row.date,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "prev_close": row.prev_close,
        "source": INDEX_SOURCE,
        "ingested_at": ingested_at,
    }


# ---------------------------------------------------------------------------
# Ingest Orchestration
# ---------------------------------------------------------------------------


def ingest_index_eod(
    payload: bytes,
    target_date: date,
    *,
    source_file: str = "",
    engine: sa.Engine | None = None,
    dry_run: bool = False,
) -> IngestReport:
    """Ingest raw index EOD CSV payload for `target_date`.

    Parameters
    ----------
    payload:
        Raw bytes of ind_close_all_DDMMYYYY.csv.
    target_date:
        Expected trading date.
    source_file:
        File label for quarantine logging.
    engine:
        SQLAlchemy engine. Defaults to `get_engine()`.
    dry_run:
        Parse and validate without database commit.

    Returns
    -------
    IngestReport
    """
    report = IngestReport(target_date=target_date)
    engine = engine or get_engine()

    # §6.2 rule 3: SHA-256 before parsing
    file_hash = sha256_bytes(payload)

    with engine.begin() as conn:
        # Check cache hit
        if runs.already_ingested(
            conn, source=INDEX_SOURCE, target_date=target_date, file_hash=file_hash
        ):
            run_id = runs.start_run(
                conn, source=INDEX_SOURCE, target_date=target_date, file_hash=file_hash
            )
            runs.finish_run(conn, run_id, status="SKIPPED_CACHED", rows=0)
            report.run_id = run_id
            report.status = "SKIPPED_CACHED"
            report.skipped_cached = True
            report.log()
            return report

        # Open run row
        run_id = runs.start_run(
            conn, source=INDEX_SOURCE, target_date=target_date, file_hash=file_hash
        )
        report.run_id = run_id

        # Parse rows
        try:
            rows = parse_index_eod_rows(payload, target_date)
        except IndexEodError as exc:
            runs.finish_run(conn, run_id, status="FAILED", rows=0, error=str(exc))
            report.status = "FAILED"
            report.abort_reason = str(exc)
            report.log()
            raise

        if dry_run:
            runs.finish_run(conn, run_id, status="OK", rows=len(rows))
            report.committed = len(rows)
            report.status = "OK"
            log.info("index_eod %s: --dry-run, %d rows parsed", target_date, len(rows))
            return report

        # Validate rows
        good: list[IndexEodRow] = []
        rejected: list[tuple[IndexEodRow, list[str]]] = []
        for r in rows:
            reasons = validate_index_row(r, target_date)
            if reasons:
                rejected.append((r, reasons))
            else:
                good.append(r)

        # Write quarantine rows for invalid items
        if rejected:
            _write_quarantine_rows(conn, run_id, source_file, rejected)

        # Upsert clean rows
        ingested_at = datetime.now(tz=IST)
        if good:
            conn.execute(
                _UPSERT_INDEX_BAR,
                [_index_to_params(r, ingested_at) for r in good],
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
# Fetch from NSE Archives / Cache
# ---------------------------------------------------------------------------


def fetch_payload(
    target_date: date,
    *,
    from_cache_only: bool = False,
    cache_root: Path | None = None,
) -> bytes:
    """Fetch the index EOD file for `target_date` through the disk cache."""
    root = cache_root or get_settings().cache_root
    filename = CACHE_FILE_TEMPLATE.format(date=target_date)
    with NSEClient(from_cache_only=from_cache_only, cache_root=root) as client:
        payload = client.fetch(
            INDEX_EOD_URL.format(date=target_date),
            source=CACHE_DIR,
            target_date=target_date,
            filename=filename,
        )
    if payload is None:
        raise IndexEodError(f"no index EOD data available for {target_date}")
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest NSE Index EOD CSV file (§6, Task 2.3)."
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
        report = ingest_index_eod(
            payload,
            args.date,
            source_file=source_file,
            dry_run=args.dry_run,
        )
        if report.status in ("OK", "SKIPPED_CACHED"):
            return 0
        return 1
    except Exception as exc:  # noqa: BLE001
        log.error("ingest failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
