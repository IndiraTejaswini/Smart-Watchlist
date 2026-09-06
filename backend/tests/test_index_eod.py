"""Index EOD ingest acceptance -- BUILD_PLAN task 2.3, ARCHITECTURE.md §6.

Acceptance criteria:
  - Target Schema Alignment: Uses `index_bars` with PK `(index_symbol, date)`
    matching 001_full_schema.py.
  - Robust CSV Parsing: Parses ind_close_all_DDMMYYYY.csv, strips thousands
    commas, coerces "-" to None.
  - Invariant & Bounds Validation: High >= max(Open, Close) and Low <= min(Open, Close).
    Row date matches target session date. Bad rows to ingest_quarantine with
    explicit reason (INDEX_HIGH_LT_LOW, etc.).
  - No Speculative Semantics: Canonical index names as published ('Nifty 50', etc.).
  - Idempotent & Transactional: Single engine.begin() block, SHA-256 caching
    with SKIPPED_CACHED, and ON CONFLICT (index_symbol, date) DO UPDATE.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.ingest.index_data import (
    INDEX_DATE_MISMATCH,
    INDEX_HIGH_LT_LOW,
    INDEX_HIGH_LT_OPEN_CLOSE,
    INDEX_LOW_GT_OPEN_CLOSE,
    INDEX_SOURCE,
    IndexEodRow,
    ingest_index_eod,
    parse_index_eod_rows,
    validate_index_row,
)

FIXTURES = Path(__file__).parent / "fixtures"
TARGET_DATE = date(2026, 9, 4)


def _valid_payload() -> bytes:
    return (FIXTURES / "index_eod_valid.csv").read_bytes()


def _formatted_payload() -> bytes:
    return (FIXTURES / "index_eod_formatted.csv").read_bytes()


def _bad_payload() -> bytes:
    return (FIXTURES / "index_eod_bad_ohlc.csv").read_bytes()


# ===========================================================================
# Pure half -- no database
# ===========================================================================


class TestIndexEodParsingAndValidation:
    def test_parse_index_eod_valid_csv(self) -> None:
        rows = parse_index_eod_rows(_valid_payload(), TARGET_DATE)
        assert len(rows) == 5
        names = [r.index_name for r in rows]
        assert "Nifty 50" in names
        assert "Nifty Next 50" in names
        assert "Nifty Midcap 150" in names
        assert "Nifty Smallcap 250" in names
        assert "Nifty Total Market" in names

        nifty50 = next(r for r in rows if r.index_name == "Nifty 50")
        assert nifty50.open == Decimal("25200.00")
        assert nifty50.high == Decimal("25300.00")
        assert nifty50.low == Decimal("25150.00")
        assert nifty50.close == Decimal("25250.00")
        assert nifty50.prev_close == Decimal("25200.00")
        assert nifty50.volume == 250000000
        assert nifty50.turnover == Decimal("12500.50")

    def test_parse_index_eod_formatted_csv_with_commas_and_dashes(self) -> None:
        rows = parse_index_eod_rows(_formatted_payload(), TARGET_DATE)
        assert len(rows) == 3

        nifty50 = next(r for r in rows if r.index_name == "Nifty 50")
        assert nifty50.open == Decimal("25200.00")
        assert nifty50.volume == 250000000
        assert nifty50.turnover == Decimal("12500.50")

        next50 = next(r for r in rows if r.index_name == "Nifty Next 50")
        assert next50.open == Decimal("72000.00")
        assert next50.volume is None
        assert next50.turnover is None

    def test_validate_index_row_clean(self) -> None:
        row = IndexEodRow(
            index_name="Nifty 50",
            date=TARGET_DATE,
            open=Decimal("25000.00"),
            high=Decimal("25200.00"),
            low=Decimal("24900.00"),
            close=Decimal("25100.00"),
            prev_close=Decimal("25050.00"),
        )
        assert validate_index_row(row, TARGET_DATE) == []

    def test_validate_index_row_high_lt_low(self) -> None:
        row = IndexEodRow(
            index_name="BAD",
            date=TARGET_DATE,
            open=Decimal("25000.00"),
            high=Decimal("24000.00"),
            low=Decimal("24500.00"),
            close=Decimal("24800.00"),
        )
        assert INDEX_HIGH_LT_LOW in validate_index_row(row, TARGET_DATE)

    def test_validate_index_row_high_lt_open_close(self) -> None:
        row = IndexEodRow(
            index_name="BAD",
            date=TARGET_DATE,
            open=Decimal("25500.00"),
            high=Decimal("25000.00"),
            low=Decimal("24000.00"),
            close=Decimal("24800.00"),
        )
        assert INDEX_HIGH_LT_OPEN_CLOSE in validate_index_row(row, TARGET_DATE)

    def test_validate_index_row_low_gt_open_close(self) -> None:
        row = IndexEodRow(
            index_name="BAD",
            date=TARGET_DATE,
            open=Decimal("25000.00"),
            high=Decimal("25500.00"),
            low=Decimal("24900.00"),
            close=Decimal("24500.00"),
        )
        assert INDEX_LOW_GT_OPEN_CLOSE in validate_index_row(row, TARGET_DATE)

    def test_validate_index_row_date_mismatch(self) -> None:
        row = IndexEodRow(
            index_name="BAD",
            date=date(2026, 9, 3),
            open=Decimal("25000.00"),
            high=Decimal("25500.00"),
            low=Decimal("24500.00"),
            close=Decimal("25000.00"),
        )
        assert INDEX_DATE_MISMATCH in validate_index_row(row, TARGET_DATE)


# ===========================================================================
# DB half
# ===========================================================================


def _make_engine() -> sa.Engine:
    try:
        from app.config import get_settings

        url = sa.engine.make_url(get_settings().database_url)
        test_url = url.set(database=f"{url.database}_indextest")
        maint = sa.create_engine(
            url.set(database="postgres"), isolation_level="AUTOCOMMIT"
        )
        with maint.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": test_url.database},
            ).first()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{test_url.database}"'))
        maint.dispose()
        return sa.create_engine(test_url.render_as_string(hide_password=False))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"postgres unreachable ({type(exc).__name__}); run `make up`")


@pytest.fixture(scope="module")
def pg_engine():
    engine = _make_engine()
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": engine.url.render_as_string(hide_password=False)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}"
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(pg_engine: sa.Engine) -> None:
    try:
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM ingest_quarantine"))
            conn.execute(sa.text("DELETE FROM index_bars"))
            conn.execute(
                sa.text("DELETE FROM ingest_runs WHERE source = :s"),
                {"s": INDEX_SOURCE},
            )
    except Exception:  # noqa: BLE001
        pass


class TestIndexEodIngestDB:
    def test_clean_index_eod_ingest_commits_all_rows(
        self, pg_engine: sa.Engine
    ) -> None:
        """Happy path: 5 valid rows land in index_bars with correct columns."""
        report = ingest_index_eod(_valid_payload(), TARGET_DATE, engine=pg_engine)
        assert report.status == "OK"
        assert report.committed == 5
        assert report.quarantined == 0

        with pg_engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM index_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
            nifty50 = conn.execute(
                sa.text(
                    "SELECT index_symbol, open, high, low, close, source "
                    "FROM index_bars WHERE index_symbol = 'Nifty 50' AND date = :d"
                ),
                {"d": TARGET_DATE},
            ).fetchone()

        assert count == 5
        assert nifty50 is not None
        assert nifty50[0] == "Nifty 50"
        assert nifty50[1] == Decimal("25200.00")
        assert nifty50[2] == Decimal("25300.00")
        assert nifty50[3] == Decimal("25150.00")
        assert nifty50[4] == Decimal("25250.00")
        assert nifty50[5] == INDEX_SOURCE

    def test_formatted_numbers_ingested_accurately(
        self, pg_engine: sa.Engine
    ) -> None:
        report = ingest_index_eod(_formatted_payload(), TARGET_DATE, engine=pg_engine)
        assert report.status == "OK"
        assert report.committed == 3

        with pg_engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT open, high, close FROM index_bars "
                    "WHERE index_symbol = 'Nifty Next 50' AND date = :d"
                ),
                {"d": TARGET_DATE},
            ).fetchone()
        assert row is not None
        assert row[0] == Decimal("72000.00")
        assert row[1] == Decimal("72500.00")
        assert row[2] == Decimal("72300.00")

    def test_bad_ohlc_quarantined_valid_committed(
        self, pg_engine: sa.Engine
    ) -> None:
        """4 malformed rows land in ingest_quarantine; 1 clean row commits."""
        report = ingest_index_eod(_bad_payload(), TARGET_DATE, engine=pg_engine)
        assert report.status == "OK"
        assert report.committed == 1
        assert report.quarantined == 4

        with pg_engine.connect() as conn:
            committed_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM index_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
            qrows = conn.execute(
                sa.text(
                    "SELECT rejection_reason, raw_payload::text FROM ingest_quarantine "
                    "WHERE ingest_run_id = :rid"
                ),
                {"rid": report.run_id},
            ).fetchall()

        assert committed_count == 1
        assert len(qrows) == 4
        reasons = [r[0] for r in qrows]
        assert any(INDEX_HIGH_LT_LOW in r for r in reasons)
        assert any(INDEX_HIGH_LT_OPEN_CLOSE in r for r in reasons)
        assert any(INDEX_LOW_GT_OPEN_CLOSE in r for r in reasons)
        assert any(INDEX_DATE_MISMATCH in r for r in reasons)

    def test_sha256_duplicate_run_is_skipped_cached(
        self, pg_engine: sa.Engine
    ) -> None:
        report1 = ingest_index_eod(_valid_payload(), TARGET_DATE, engine=pg_engine)
        assert report1.status == "OK"

        report2 = ingest_index_eod(_valid_payload(), TARGET_DATE, engine=pg_engine)
        assert report2.status == "SKIPPED_CACHED"
        assert report2.skipped_cached is True

        with pg_engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM index_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
        assert count == 5

    def test_on_conflict_updates_existing_rows(
        self, pg_engine: sa.Engine
    ) -> None:
        ingest_index_eod(_valid_payload(), TARGET_DATE, engine=pg_engine)

        # Alter Nifty 50 close price
        altered = _valid_payload().replace(b"25250.00", b"25275.00")
        report2 = ingest_index_eod(altered, TARGET_DATE, engine=pg_engine)
        assert report2.status == "OK"

        with pg_engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM index_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
            close_val = conn.execute(
                sa.text(
                    "SELECT close FROM index_bars "
                    "WHERE index_symbol = 'Nifty 50' AND date = :d"
                ),
                {"d": TARGET_DATE},
            ).scalar_one()

        assert count == 5
        assert close_val == Decimal("25275.00")
