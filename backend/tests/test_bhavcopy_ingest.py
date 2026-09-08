"""Bhavcopy ingest acceptance -- BUILD_PLAN task 2.1.

Two halves, mirroring the pattern of test_symbol_master.py and test_calendar.py:

  Pure half -- validates without a database.  Covers validate_bar exhaustively
  against inline Bar fixtures.  Runs offline.

  DB half -- requires Postgres.  Skipped (not failed) when the database is
  unreachable, so the CI suite still passes offline.  Uses a throwaway schema
  prefix to avoid touching the working database.

Acceptance criteria from BUILD_PLAN 2.1:
  - Re-running the same date produces identical counts and no duplicates.
  - A corrupted fixture aborts without committing and rows land in quarantine.
  - A hash-matched re-run reports SKIPPED_CACHED.

Additional DB-half assertions (all follow from §6.2):
  - Quarantine row is written with the correct rejection_reason code.
  - MUHURAT session_type suppresses the count check.
  - Active-symbol floor triggers FAILED when committed rows are too few.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.ingest.bhavcopy import Bar
from app.ingest.bhavcopy_ingest import (
    HIGH_LT_LOW,
    HIGH_LT_OPEN_CLOSE,
    LOW_GT_OPEN_CLOSE,
    SOURCE,
    VOLUME_NEGATIVE,
    BhavcopyAbortError,
    ingest_bhavcopy,
    validate_bar,
)

FIXTURES = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TARGET_DATE = date(2026, 9, 4)


def _bar(
    symbol: str = "TEST",
    *,
    open: str = "100.00",
    high: str = "110.00",
    low: str = "90.00",
    close: str = "105.00",
    volume: int = 100_000,
    prev_close: str = "100.00",
) -> Bar:
    """Construct a valid Bar with keyword overrides."""
    return Bar(
        symbol=symbol,
        date=TARGET_DATE,
        series="EQ",
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        prev_close=Decimal(prev_close),
        last=Decimal(close),
        volume=volume,
        turnover=Decimal("10500000.00"),
        trades=2000,
    )


# ===========================================================================
# Pure half -- no database
# ===========================================================================


class TestValidateBar:
    """§6.2 rule 4 -- all four rejection codes, plus the happy path."""

    def test_clean_bar_passes(self) -> None:
        assert validate_bar(_bar()) == []

    def test_high_lt_low(self) -> None:
        # high=80, low=90 => HIGH_LT_LOW
        bar = _bar(high="80.00", low="90.00")
        reasons = validate_bar(bar)
        assert HIGH_LT_LOW in reasons

    def test_high_lt_open(self) -> None:
        # open=120 > high=110 => HIGH_LT_OPEN_CLOSE
        bar = _bar(high="110.00", low="90.00", open="120.00", close="105.00")
        reasons = validate_bar(bar)
        assert HIGH_LT_OPEN_CLOSE in reasons

    def test_high_lt_close(self) -> None:
        # close=115 > high=110 => HIGH_LT_OPEN_CLOSE
        bar = _bar(high="110.00", low="90.00", open="100.00", close="115.00")
        reasons = validate_bar(bar)
        assert HIGH_LT_OPEN_CLOSE in reasons

    def test_low_gt_open(self) -> None:
        # open=85 < low=90 => LOW_GT_OPEN_CLOSE
        bar = _bar(high="110.00", low="90.00", open="85.00", close="105.00")
        reasons = validate_bar(bar)
        assert LOW_GT_OPEN_CLOSE in reasons

    def test_low_gt_close(self) -> None:
        # close=88 < low=90 => LOW_GT_OPEN_CLOSE
        bar = _bar(high="110.00", low="90.00", open="100.00", close="88.00")
        reasons = validate_bar(bar)
        assert LOW_GT_OPEN_CLOSE in reasons

    def test_volume_negative(self) -> None:
        bar = _bar(volume=-1)
        reasons = validate_bar(bar)
        assert VOLUME_NEGATIVE in reasons

    def test_multiple_reasons_collected(self) -> None:
        # high=80 < low=90 AND high=80 < open=100 -- two reasons at once
        bar = _bar(high="80.00", low="90.00", open="100.00", close="79.00")
        reasons = validate_bar(bar)
        assert HIGH_LT_LOW in reasons
        assert HIGH_LT_OPEN_CLOSE in reasons

    def test_none_fields_do_not_trigger_rejection(self) -> None:
        """Thinly-traded days may have None prices; no rejection should fire."""
        bar = Bar(
            symbol="THINCO",
            date=TARGET_DATE,
            series="EQ",
            open=None,
            high=None,
            low=None,
            close=None,
            prev_close=None,
            last=None,
            volume=None,
            turnover=None,
            trades=None,
        )
        assert validate_bar(bar) == []

    def test_volume_zero_is_valid(self) -> None:
        """Volume = 0 means no trades, not a data error (§6.2 rule 4: volume >= 0)."""
        bar = _bar(volume=0)
        assert validate_bar(bar) == []

    def test_high_eq_low_is_valid(self) -> None:
        """A limit-up / limit-down day can have high == low == open == close."""
        bar = _bar(high="100.00", low="100.00", open="100.00", close="100.00")
        assert validate_bar(bar) == []


# ===========================================================================
# DB half
# ===========================================================================

# All DB tests share one migration-applied engine, created once per module so
# the heavy alembic round-trip runs only once.


def _make_engine() -> sa.Engine:
    try:
        from app.config import get_settings

        url = sa.engine.make_url(get_settings().database_url)
        # Use a dedicated test database to avoid touching the working schema.
        test_url = url.set(database=f"{url.database}_bhavtest")
        maint = sa.create_engine(
            url.set(database="postgres"), isolation_level="AUTOCOMMIT",
            connect_args={"connect_timeout": 5},
        )
        with maint.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": test_url.database},
            ).first()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{test_url.database}"'))
        maint.dispose()
        return sa.create_engine(
            test_url.render_as_string(hide_password=False), connect_args={"connect_timeout": 5}
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"postgres unreachable ({type(exc).__name__}); run `make up`")


@pytest.fixture(scope="module")
def pg_engine():
    """Module-scoped engine against the throwaway test database."""
    engine = _make_engine()
    # Apply the full schema via alembic.
    import subprocess
    import sys
    from pathlib import Path

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
    """Truncate the relevant tables before every DB test for isolation.

    DELETE is used instead of TRUNCATE to avoid needing CASCADE or touching
    tables not under test.  Runs in insertion order to satisfy FKs.
    """
    # Only run when the pg_engine fixture is actually in play.
    try:
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM ingest_quarantine"))
            conn.execute(sa.text("DELETE FROM daily_bars"))
            conn.execute(sa.text("DELETE FROM ingest_runs WHERE source = 'bhavcopy'"))
            conn.execute(sa.text("DELETE FROM instruments"))
    except Exception:  # noqa: BLE001
        pass  # fixture not in scope for pure tests


# ── Fixture payloads ────────────────────────────────────────────────────────

def _valid_payload() -> bytes:
    return (FIXTURES / "bhavcopy_valid_10rows.csv").read_bytes()


def _one_bad_payload() -> bytes:
    return (FIXTURES / "bhavcopy_one_bad_row.csv").read_bytes()


def _all_bad_payload() -> bytes:
    return (FIXTURES / "bhavcopy_all_bad_rows.csv").read_bytes()


# Marker to skip the whole class when pg_engine is not available.
pg = pytest.mark.usefixtures("pg_engine")


class TestIngestBhavcopydDB:
    """DB-backed acceptance tests for ingest_bhavcopy."""

    def test_first_ingest_commits_all_valid_rows(self, pg_engine: sa.Engine) -> None:
        """Happy path: 10 valid rows all land in daily_bars."""
        report = ingest_bhavcopy(
            _valid_payload(), TARGET_DATE, engine=pg_engine
        )
        assert report.status == "OK"
        assert report.committed == 10
        assert report.quarantined == 0

        with pg_engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM daily_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
        assert count == 10

    def test_idempotent_rerun_produces_same_count_no_duplicates(
        self, pg_engine: sa.Engine
    ) -> None:
        """§6.2 rule 1 + acceptance criterion: re-running same date is safe."""
        ingest_bhavcopy(_valid_payload(), TARGET_DATE, engine=pg_engine)

        # Second run with same payload but different bytes (e.g. re-downloaded)
        # -- we change nothing, so the hash matches and we get SKIPPED_CACHED.
        # But we also need to test the idempotent path when the hash is NEW
        # (e.g. a different source produced the same logical data).
        # Simulate that by calling directly with the same payload again.
        report2 = ingest_bhavcopy(_valid_payload(), TARGET_DATE, engine=pg_engine)
        # The hash matched the first OK run, so this is a cache hit.
        assert report2.skipped_cached is True
        assert report2.status == "SKIPPED_CACHED"

        with pg_engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM daily_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
        assert count == 10  # still exactly 10, no duplicates

    def test_skipped_cached_writes_ingest_run_row(self, pg_engine: sa.Engine) -> None:
        """§6.2 rule 2: even a cache-hit produces an ingest_runs row."""
        ingest_bhavcopy(_valid_payload(), TARGET_DATE, engine=pg_engine)
        report = ingest_bhavcopy(_valid_payload(), TARGET_DATE, engine=pg_engine)
        assert report.run_id is not None

        with pg_engine.connect() as conn:
            status = conn.execute(
                sa.text(
                    "SELECT status FROM ingest_runs WHERE id = :rid"
                ),
                {"rid": report.run_id},
            ).scalar_one()
        assert status == "SKIPPED_CACHED"

    def test_one_bad_row_quarantined_rest_committed(
        self, pg_engine: sa.Engine
    ) -> None:
        """§6.2 rules 4+5: the bad row lands in quarantine; the rest commit."""
        report = ingest_bhavcopy(
            _one_bad_payload(), TARGET_DATE, engine=pg_engine
        )
        assert report.status == "OK"
        assert report.committed == 99
        assert report.quarantined == 1

        with pg_engine.connect() as conn:
            bar_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM daily_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
            qrow = conn.execute(
                sa.text(
                    "SELECT rejection_reason, raw_payload::text"
                    " FROM ingest_quarantine"
                    " WHERE ingest_run_id = :rid"
                ),
                {"rid": report.run_id},
            ).fetchall()

        assert bar_count == 99
        assert len(qrow) == 1
        assert HIGH_LT_LOW in qrow[0][0]
        # The bad symbol must appear in the JSONB payload.
        assert "BADBAR" in qrow[0][1]

    def test_all_bad_rows_aborts_and_no_daily_bars_committed(
        self, pg_engine: sa.Engine
    ) -> None:
        """§6.2 rule 6 (quarantine ratio): abort rolls back daily_bars."""
        with pytest.raises(BhavcopyAbortError):
            ingest_bhavcopy(_all_bad_payload(), TARGET_DATE, engine=pg_engine)

        with pg_engine.connect() as conn:
            bar_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM daily_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
            failed_run = conn.execute(
                sa.text(
                    "SELECT status, error FROM ingest_runs"
                    " WHERE source = :src ORDER BY started_at DESC LIMIT 1"
                ),
                {"src": SOURCE},
            ).fetchone()

        assert bar_count == 0
        assert failed_run is not None
        assert failed_run[0] == "FAILED"
        assert "QUARANTINE_ABORT_FRAC" in (failed_run[1] or "")

    def test_quarantine_rows_survive_abort(self, pg_engine: sa.Engine) -> None:
        """Bad rows are still written to quarantine even when the abort fires.

        The audit trail must be complete even when daily_bars is rolled back.
        """
        try:
            ingest_bhavcopy(_all_bad_payload(), TARGET_DATE, engine=pg_engine)
        except BhavcopyAbortError:
            pass

        with pg_engine.connect() as conn:
            q_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM ingest_quarantine")
            ).scalar_one()
        # 5 rows in the all-bad fixture, all quarantined
        assert q_count == 5

    def test_muhurat_session_suppresses_count_check(
        self, pg_engine: sa.Engine
    ) -> None:
        """§6.2 / §6.1: short file on a MUHURAT day must not abort."""
        # No instruments are loaded, so active_count = 0.
        # For a REGULAR session with 0 active instruments the floor check
        # is skipped (floor = 0), so we use MUHURAT explicitly to test
        # the suppression path and confirm it reaches OK status.
        report = ingest_bhavcopy(
            _valid_payload(),
            TARGET_DATE,
            session_type="MUHURAT",
            engine=pg_engine,
        )
        assert report.status == "OK"

    def test_half_day_session_suppresses_count_check(
        self, pg_engine: sa.Engine
    ) -> None:
        report = ingest_bhavcopy(
            _valid_payload(),
            TARGET_DATE,
            session_type="HALF_DAY",
            engine=pg_engine,
        )
        assert report.status == "OK"

    def test_run_row_records_file_hash(self, pg_engine: sa.Engine) -> None:
        """§6.2 rule 2+3: the ingest_runs row carries the SHA-256 hash."""
        from app.ingest.nse_client import sha256_bytes

        payload = _valid_payload()
        expected_hash = sha256_bytes(payload)
        report = ingest_bhavcopy(payload, TARGET_DATE, engine=pg_engine)

        with pg_engine.connect() as conn:
            stored_hash = conn.execute(
                sa.text("SELECT file_hash FROM ingest_runs WHERE id = :rid"),
                {"rid": report.run_id},
            ).scalar_one()
        assert stored_hash == expected_hash

    def test_second_ingest_with_different_hash_upserts(
        self, pg_engine: sa.Engine
    ) -> None:
        """If the payload changes (different hash) a new run upserts, not skips."""
        # First ingest
        ingest_bhavcopy(_valid_payload(), TARGET_DATE, engine=pg_engine)

        # Construct a payload with a different hash but same symbols.
        # Add a trailing space to a cell to change bytes without breaking CSV.
        altered = _valid_payload().replace(b"RELIANCE", b"RELIANCE ")
        report2 = ingest_bhavcopy(altered, TARGET_DATE, engine=pg_engine)
        assert report2.skipped_cached is False
        assert report2.status == "OK"
        # Symbols still match: upsert means same 10 rows, no duplicates.
        with pg_engine.connect() as conn:
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM daily_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
        assert count == 10

    def test_active_symbol_floor_abort(self, pg_engine: sa.Engine) -> None:
        """§6.2 rule 6: abort if rows < ACTIVE_ROW_FLOOR_FRAC * active_instruments."""
        # Insert 50 active instruments into the DB: floor = int(0.98 * 50) = 49
        with pg_engine.begin() as conn:
            for i in range(50):
                conn.execute(
                    sa.text(
                        "INSERT INTO instruments (symbol, name, series, sector_source, is_active) "
                        "VALUES (:sym, :name, 'EQ', 'UNASSIGNED', TRUE)"
                    ),
                    {"sym": f"INST{i:03d}", "name": f"Instrument {i}"},
                )

        # Ingesting 10 rows on REGULAR session must abort against floor of 49
        with pytest.raises(BhavcopyAbortError) as exc_info:
            ingest_bhavcopy(
                _valid_payload(),
                TARGET_DATE,
                session_type="REGULAR",
                engine=pg_engine,
            )
        assert "active-symbol floor" in str(exc_info.value)

        with pg_engine.connect() as conn:
            bar_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM daily_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
        assert bar_count == 0

    def test_rolling_median_deviation_abort(self, pg_engine: sa.Engine) -> None:
        """§6.2 rule 6: abort if deviation from 5-run median > ROW_COUNT_DEVIATION."""
        # Seed 5 prior successful runs of 100 rows each
        with pg_engine.begin() as conn:
            for i in range(5):
                d = date(2026, 8, 25 + i)
                conn.execute(
                    sa.text(
                        "INSERT INTO ingest_runs "
                        "(source, target_date, status, rows, started_at, finished_at) "
                        "VALUES (:src, :d, 'OK', 100, NOW(), NOW())"
                    ),
                    {"src": SOURCE, "d": d},
                )

        # Ingesting 10 rows has deviation = abs(10 - 100)/100 = 90% > 20%
        with pytest.raises(BhavcopyAbortError) as exc_info:
            ingest_bhavcopy(
                _valid_payload(),
                TARGET_DATE,
                session_type="REGULAR",
                engine=pg_engine,
            )
        assert "deviates" in str(exc_info.value)
        assert "ROW_COUNT_DEVIATION" in str(exc_info.value)

        with pg_engine.connect() as conn:
            bar_count = conn.execute(
                sa.text("SELECT COUNT(*) FROM daily_bars WHERE date = :d"),
                {"d": TARGET_DATE},
            ).scalar_one()
        assert bar_count == 0

    def test_floor_and_median_suppressed_on_muhurat_even_with_low_rows(
        self, pg_engine: sa.Engine
    ) -> None:
        """§6.2 / §6.1: active symbol floor and rolling median are both suppressed on MUHURAT."""
        with pg_engine.begin() as conn:
            # Seed 50 active instruments (would fail floor of 49)
            for i in range(50):
                conn.execute(
                    sa.text(
                        "INSERT INTO instruments (symbol, name, series, sector_source, is_active) "
                        "VALUES (:sym, :name, 'EQ', 'UNASSIGNED', TRUE)"
                    ),
                    {"sym": f"INST{i:03d}", "name": f"Instrument {i}"},
                )
            # Seed prior runs with 1000 rows (would fail median check)
            for i in range(5):
                d = date(2026, 8, 25 + i)
                conn.execute(
                    sa.text(
                        "INSERT INTO ingest_runs "
                        "(source, target_date, status, rows, started_at, finished_at) "
                        "VALUES (:src, :d, 'OK', 1000, NOW(), NOW())"
                    ),
                    {"src": SOURCE, "d": d},
                )

        # Ingesting 10 rows on MUHURAT must succeed despite floor and median
        report = ingest_bhavcopy(
            _valid_payload(),
            TARGET_DATE,
            session_type="MUHURAT",
            engine=pg_engine,
        )
        assert report.status == "OK"
        assert report.committed == 10

