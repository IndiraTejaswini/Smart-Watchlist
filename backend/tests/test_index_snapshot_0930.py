"""Rule R2 acceptance tests for the 09:30 index snapshot pipeline."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.ingest.index_snapshot import (
    BROKER_1M,
    ESTIMATED_FROM_OPEN,
    LIVE_0930,
    PRIMARY_INDEXES,
    backfill_index_snapshots_0930,
    capture_index_snapshot_0930,
)

BACKEND = Path(__file__).resolve().parents[1]


def _engine() -> sa.Engine:
    try:
        from app.config import get_settings

        url = sa.engine.make_url(get_settings().database_url)
        test_url = url.set(database=f"{url.database}_snapshot0930test")
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
        conn.execute(sa.text("DELETE FROM index_snapshots_0930"))
        conn.execute(sa.text("DELETE FROM index_bars"))


def _seed_opens(engine: sa.Engine, trading_date: date) -> None:
    with engine.begin() as conn:
        for symbol, value in zip(PRIMARY_INDEXES, (100, 200), strict=True):
            conn.execute(
                sa.text(
                    "INSERT INTO index_bars "
                    "(index_symbol, date, open, source, ingested_at) "
                    "VALUES (:symbol, :date, :open, 'test', CURRENT_TIMESTAMP)"
                ),
                {"symbol": symbol, "date": trading_date, "open": value},
            )


def _flags(engine: sa.Engine, trading_date: date) -> dict[str, str]:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                sa.text(
                    "SELECT index_symbol, quality_flag FROM index_snapshots_0930 "
                    "WHERE trading_date = :date"
                ),
                {"date": trading_date},
            ).all()
        )


def test_full_priority_cascade(pg_engine: sa.Engine) -> None:
    trading_date = date(2026, 9, 4)
    _seed_opens(pg_engine, trading_date)
    capture_index_snapshot_0930(
        trading_date,
        engine=pg_engine,
        live_provider={("Nifty 50", trading_date): Decimal("101")},
        broker_provider={("Nifty Total Market", trading_date): Decimal("201")},
    )
    assert _flags(pg_engine, trading_date) == {
        "Nifty 50": LIVE_0930,
        "Nifty Total Market": BROKER_1M,
    }

    next_date = date(2026, 9, 7)
    _seed_opens(pg_engine, next_date)
    capture_index_snapshot_0930(next_date, engine=pg_engine)
    assert _flags(pg_engine, next_date) == {
        symbol: ESTIMATED_FROM_OPEN for symbol in PRIMARY_INDEXES
    }


def test_lower_priority_sources_do_not_clobber(pg_engine: sa.Engine) -> None:
    trading_date = date(2026, 9, 4)
    _seed_opens(pg_engine, trading_date)
    capture_index_snapshot_0930(
        trading_date,
        engine=pg_engine,
        broker_provider={("Nifty 50", trading_date): Decimal("101")},
    )
    capture_index_snapshot_0930(trading_date, engine=pg_engine)
    assert _flags(pg_engine, trading_date)["Nifty 50"] == BROKER_1M

    capture_index_snapshot_0930(
        trading_date,
        engine=pg_engine,
        live_provider={("Nifty 50", trading_date): Decimal("102")},
    )
    capture_index_snapshot_0930(trading_date, engine=pg_engine)
    assert _flags(pg_engine, trading_date)["Nifty 50"] == LIVE_0930


def test_backfill_is_complete_for_each_trading_date(pg_engine: sa.Engine) -> None:
    dates = (date(2026, 9, 3), date(2026, 9, 4))
    for trading_date in dates:
        _seed_opens(pg_engine, trading_date)
    assert backfill_index_snapshots_0930(dates, engine=pg_engine) == 4
    with pg_engine.connect() as conn:
        assert conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM index_snapshots_0930 "
                "WHERE trading_date = ANY(:dates)"
            ),
            {"dates": list(dates)},
        ).scalar_one() == 4


def test_health_surfaces_estimated_count(pg_engine: sa.Engine, monkeypatch) -> None:
    trading_date = date(2026, 9, 4)
    _seed_opens(pg_engine, trading_date)
    capture_index_snapshot_0930(trading_date, engine=pg_engine)

    import app.main

    monkeypatch.setattr(app.main, "get_engine", lambda: pg_engine)
    response = TestClient(app.main.create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json()["estimated_from_open_count"] == 2
