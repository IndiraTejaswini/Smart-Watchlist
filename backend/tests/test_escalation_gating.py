"""Acceptance tests for calendar-gated polling and escalation guardrails."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.ingest.polling import IST, SOURCE, poll_bhavcopy
from app.pipeline.baseline import run_baseline

BACKEND = Path(__file__).resolve().parents[1]
TRADING_DATE = date(2026, 9, 4)
HOLIDAY = date(2026, 9, 5)


def _engine() -> sa.Engine:
    try:
        from app.config import get_settings

        url = sa.engine.make_url(get_settings().database_url)
        test_url = url.set(database=f"{url.database}_escalationtest")
        maintenance = sa.create_engine(
            url.set(database="postgres"), isolation_level="AUTOCOMMIT",
            connect_args={"connect_timeout": 5},
        )
        with maintenance.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": test_url.database},
            ).first()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{test_url.database}"'))
        maintenance.dispose()
        return sa.create_engine(
            test_url.render_as_string(hide_password=False), connect_args={"connect_timeout": 5}
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"postgres unreachable ({type(exc).__name__}); run `make up`")


@pytest.fixture(scope="module")
def pg_engine() -> sa.Engine:
    engine = _engine()
    env = {**os.environ, "DATABASE_URL": engine.url.render_as_string(hide_password=False)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}"
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean(pg_engine: sa.Engine) -> None:
    with pg_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM ingest_runs WHERE source = :source"), {"source": SOURCE})
        conn.execute(
            sa.text(
                "DELETE FROM trading_calendar WHERE calendar_date IN (:trading, :holiday)"
            ),
            {"trading": TRADING_DATE, "holiday": HOLIDAY},
        )
        conn.execute(
            sa.text(
                "INSERT INTO trading_calendar "
                "(calendar_date, is_trading_day, session_type) "
                "VALUES (:trading, TRUE, 'REGULAR'), (:holiday, FALSE, 'CLOSED')"
            ),
            {"trading": TRADING_DATE, "holiday": HOLIDAY},
        )


def test_non_trading_day_has_zero_state_churn(pg_engine: sa.Engine) -> None:
    result = poll_bhavcopy(
        HOLIDAY,
        lambda: (_ for _ in ()).throw(AssertionError()),
        engine=pg_engine,
    )
    assert result.status == "SKIPPED_NON_TRADING_DAY"
    with pg_engine.connect() as conn:
        assert conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM ingest_runs "
                "WHERE source = :source AND target_date = :target_date"
            ),
            {"source": SOURCE, "target_date": HOLIDAY},
        ).scalar_one() == 0


def test_four_failures_after_cutoff_escalate(pg_engine: sa.Engine) -> None:
    now = datetime(2026, 9, 4, 20, 31, tzinfo=IST)

    def fail() -> bytes:
        raise OSError("missing")

    results = [poll_bhavcopy(TRADING_DATE, fail, now=now, engine=pg_engine) for _ in range(4)]
    assert [result.status for result in results] == ["FAILED", "FAILED", "FAILED", "ESCALATED"]


def test_baseline_refuses_escalated_date(pg_engine: sa.Engine) -> None:
    with pg_engine.begin() as conn:
        run_id = conn.execute(
            sa.text(
                "INSERT INTO ingest_runs "
                "(source, target_date, status, started_at) "
                "VALUES (:source, :target_date, 'ESCALATED', CURRENT_TIMESTAMP) RETURNING id"
            ),
            {"source": SOURCE, "target_date": TRADING_DATE},
        ).scalar_one()
    from app.ingest.polling import EscalatedIngestError

    with pytest.raises(EscalatedIngestError):
        run_baseline(TRADING_DATE, lambda _: run_id, engine=pg_engine)


def test_market_status_exposes_escalation(pg_engine: sa.Engine, monkeypatch) -> None:
    with pg_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO ingest_runs "
                "(source, target_date, status, started_at) "
                "VALUES (:source, :target_date, 'ESCALATED', CURRENT_TIMESTAMP)"
            ),
            {"source": SOURCE, "target_date": TRADING_DATE},
        )

    import app.main

    monkeypatch.setattr(app.main, "get_engine", lambda: pg_engine)
    response = TestClient(app.main.create_app()).get("/api/market/status")
    assert response.status_code == 200
    assert response.json()["status"] == "ESCALATED"
    assert response.json()["escalated_dates"] == [str(TRADING_DATE)]
