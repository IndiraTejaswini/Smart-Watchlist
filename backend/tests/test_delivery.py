"""Delivery data ingest acceptance -- BUILD_PLAN task 2.2, ARCHITECTURE.md §6, §8.3.

Acceptance criteria:
  - Core Row Invariant: deliverable_qty <= traded_qty for 100% of committed rows.
    Any row violating this must be rejected and routed to ingest_quarantine
    (reason: DELIV_GT_TRADED).
  - File-Level Stale/Holiday Check: Per Task 0.1 findings, validate DATE1
    against the expected target session date before parsing rows.  If DATE1 is
    from a prior trading day (holiday HTTP 200 payload), quarantine the entire
    payload to data/cache/delivery_stale/ and exit with SKIPPED_HOLIDAY_STALE.
    Do not commit any rows.
  - Transactional Integrity & Idempotency: Upsert records atomically within an
    engine.begin() block with SHA-256 caching in ingest_runs and
    ON CONFLICT (symbol, date) DO UPDATE.
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

from app.ingest.delivery import (
    DELIV_GT_TRADED,
    DELIV_QTY_NEGATIVE,
    DELIVERY_SOURCE,
    IN_SCOPE_SERIES,
    TRADED_QTY_NEGATIVE,
    DeliveryRow,
    extract_content_date,
    ingest_delivery,
    parse_delivery_rows,
    validate_delivery_row,
)

FIXTURES = Path(__file__).parent / "fixtures"
TARGET_DATE = date(2026, 9, 4)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_payload() -> bytes:
    return (FIXTURES / "delivery_valid_10rows.csv").read_bytes()


def _one_bad_payload() -> bytes:
    return (FIXTURES / "delivery_one_bad_row.csv").read_bytes()


def _stale_payload() -> bytes:
    return (FIXTURES / "delivery_stale_holiday.csv").read_bytes()


# ===========================================================================
# Pure half -- no database
# ===========================================================================


class TestDeliveryParsingAndValidation:
    def test_extract_content_date_valid(self) -> None:
        content_date = extract_content_date(_valid_payload())
        assert content_date == TARGET_DATE

    def test_extract_content_date_stale(self) -> None:
        content_date = extract_content_date(_stale_payload())
        assert content_date == date(2026, 9, 3)

    def test_extract_content_date_empty_or_malformed(self) -> None:
        assert extract_content_date(b"") is None
        assert extract_content_date(b"SOME,HEADER\nval1,val2\n") is None

    def test_validate_delivery_row_clean(self) -> None:
        row = DeliveryRow(
            symbol="INFY",
            date=TARGET_DATE,
            series="EQ",
            traded_qty=1000,
            deliverable_qty=500,
            delivery_pct=Decimal("50.00"),
        )
        assert validate_delivery_row(row) == []

    def test_validate_delivery_row_equal_traded_and_deliverable(self) -> None:
        row = DeliveryRow(
            symbol="INFY",
            date=TARGET_DATE,
            series="EQ",
            traded_qty=1000,
            deliverable_qty=1000,
            delivery_pct=Decimal("100.00"),
        )
        assert validate_delivery_row(row) == []

    def test_validate_delivery_row_deliv_gt_traded(self) -> None:
        row = DeliveryRow(
            symbol="BADDELIV",
            date=TARGET_DATE,
            series="EQ",
            traded_qty=1000,
            deliverable_qty=1500,
            delivery_pct=Decimal("150.00"),
        )
        reasons = validate_delivery_row(row)
        assert DELIV_GT_TRADED in reasons

    def test_validate_delivery_row_traded_negative(self) -> None:
        row = DeliveryRow(
            symbol="BAD",
            date=TARGET_DATE,
            series="EQ",
            traded_qty=-100,
            deliverable_qty=50,
            delivery_pct=Decimal("50.00"),
        )
        assert TRADED_QTY_NEGATIVE in validate_delivery_row(row)

    def test_validate_delivery_row_deliverable_negative(self) -> None:
        row = DeliveryRow(
            symbol="BAD",
            date=TARGET_DATE,
            series="EQ",
            traded_qty=100,
            deliverable_qty=-50,
            delivery_pct=Decimal("50.00"),
        )
        assert DELIV_QTY_NEGATIVE in validate_delivery_row(row)

    def test_validate_delivery_row_none_deliverable_passes(self) -> None:
        """Series like BE where deliverable is literal '-' (None) passes validation."""
        row = DeliveryRow(
            symbol="3IINFOLTD",
            date=TARGET_DATE,
            series="BE",
            traded_qty=161133,
            deliverable_qty=None,
            delivery_pct=None,
        )
        assert validate_delivery_row(row) == []

    def test_parse_delivery_rows_filters_series(self) -> None:
        header = (
            b"SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, "
            b"LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, "
            b"NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
        )
        r1 = (
            b"INFY, EQ, 04-Sep-2026, 1795.0, 1800.0, 1830.0, 1785.0, 1812.0, "
            b"1810.0, 1810.0, 1000, 18.1, 100, 500, 50.0\n"
        )
        r2 = (
            b"GOVT1, GS, 04-Sep-2026, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, "
            b"100.0, 10, 0.1, 1, 10, 100.0\n"
        )
        r3 = (
            b"SME1, SM, 04-Sep-2026, 50.0, 50.0, 52.0, 49.0, 51.0, 51.0, "
            b"50.5, 5000, 2.5, 20, 3000, 60.0\n"
        )
        sample_csv = header + r1 + r2 + r3
        rows = parse_delivery_rows(sample_csv, TARGET_DATE)
        assert len(rows) == 1
        assert rows[0].symbol == "INFY"
        assert rows[0].series in IN_SCOPE_SERIES


# ===========================================================================
# DB half
# ===========================================================================


def _make_engine() -> sa.Engine:
    try:
        from app.config import get_settings

        url = sa.engine.make_url(get_settings().database_url)
        test_url = url.set(database=f"{url.database}_delivtest")
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
            conn.execute(sa.text("DELETE FROM delivery_stats"))
            conn.execute(
                sa.text("DELETE FROM ingest_runs WHERE source = :s"),
                {"s": DELIVERY_SOURCE},
            )
    except Exception:  # noqa: BLE001
        pass


class TestDeliveryIngestDB:
    def test_clean_delivery_ingest_commits_all_valid_rows(
        self, pg_engine: sa.Engine
    ) -> None:
        """Happy path: 10 valid rows all land in delivery_stats."""
        report = ingest_delivery(_valid_payload(), TARGET_DATE, engine=pg_engine)
        assert report.status == "OK"
        assert report.committed == 10
        assert report.quarantined == 0

        with pg_engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM delivery_stats WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
            # Verify row invariant: deliverable_qty <= traded_qty for 100% of committed rows
            violators = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM delivery_stats "
                    "WHERE date = :d AND deliverable_qty > traded_qty"
                ),
                {"d": TARGET_DATE},
            ).scalar_one()

        assert count == 10
        assert violators == 0

    def test_stale_holiday_payload_quarantines_and_exits_skipped_holiday_stale(
        self, pg_engine: sa.Engine, tmp_path: Path
    ) -> None:
        """File-level stale check: DATE1 != target_date moves file to delivery_stale and exits."""
        report = ingest_delivery(
            _stale_payload(),
            TARGET_DATE,
            engine=pg_engine,
            cache_root=tmp_path,
        )
        assert report.status == "SKIPPED_HOLIDAY_STALE"
        assert report.committed == 0

        # Verify no rows committed to delivery_stats
        with pg_engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM delivery_stats WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
            run_status = conn.execute(
                sa.text(
                    "SELECT status FROM ingest_runs WHERE id = :rid"
                ),
                {"rid": report.run_id},
            ).scalar_one()

        assert count == 0
        assert run_status == "SKIPPED_HOLIDAY_STALE"

        # Verify payload quarantined to data/cache/delivery_stale/{target_date}/
        stale_dir = tmp_path / "delivery_stale" / TARGET_DATE.isoformat()
        assert stale_dir.is_dir()
        quarantined_files = list(stale_dir.glob("*.csv"))
        assert len(quarantined_files) == 1

    def test_deliv_gt_traded_row_routed_to_quarantine(
        self, pg_engine: sa.Engine
    ) -> None:
        """deliverable_qty > traded_qty rejected to ingest_quarantine with DELIV_GT_TRADED."""
        report = ingest_delivery(_one_bad_payload(), TARGET_DATE, engine=pg_engine)
        assert report.status == "OK"
        assert report.committed == 10
        assert report.quarantined == 1

        with pg_engine.connect() as conn:
            bar_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM delivery_stats WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
            qrows = conn.execute(
                sa.text(
                    "SELECT rejection_reason, raw_payload::text FROM ingest_quarantine "
                    "WHERE ingest_run_id = :rid"
                ),
                {"rid": report.run_id},
            ).fetchall()

        assert bar_count == 10
        assert len(qrows) == 1
        assert DELIV_GT_TRADED in qrows[0][0]
        assert "BADDELIV" in qrows[0][1]

    def test_idempotent_rerun_with_same_hash_is_skipped_cached(
        self, pg_engine: sa.Engine
    ) -> None:
        """SHA-256 matched re-run exits SKIPPED_CACHED."""
        report1 = ingest_delivery(_valid_payload(), TARGET_DATE, engine=pg_engine)
        assert report1.status == "OK"

        report2 = ingest_delivery(_valid_payload(), TARGET_DATE, engine=pg_engine)
        assert report2.status == "SKIPPED_CACHED"
        assert report2.skipped_cached is True

        with pg_engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM delivery_stats WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
        assert count == 10

    def test_upsert_on_conflict_updates_existing_rows(
        self, pg_engine: sa.Engine
    ) -> None:
        """Re-ingesting modified data for the same date updates rows without duplicates."""
        ingest_delivery(_valid_payload(), TARGET_DATE, engine=pg_engine)

        # Alter traded_qty in the payload for RELIANCE
        altered = _valid_payload().replace(b"1500000, 43800.00", b"1600000, 43800.00")
        report2 = ingest_delivery(altered, TARGET_DATE, engine=pg_engine)
        assert report2.status == "OK"

        with pg_engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM delivery_stats WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
            reliance_traded = conn.execute(
                sa.text(
                    "SELECT traded_qty FROM delivery_stats WHERE symbol = 'RELIANCE' AND date = :d"
                ),
                {"d": TARGET_DATE},
            ).scalar_one()

        assert count == 10
        assert reliance_traded == 1600000
