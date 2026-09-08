"""Migration acceptance — BUILD_PLAN task 0.5.

`alembic upgrade head` and `alembic downgrade base` must both succeed, and the
round trip must be repeatable: a downgrade that leaves an object behind makes
the next upgrade fail on a clean-looking database, which is the sort of thing
discovered at the worst possible moment.

Requires the compose stack. Skipped, not failed, when Postgres is unreachable,
so the rest of the suite still runs offline.

These tests run against a throwaway `<db>_migrationtest` database, never the
configured one: `downgrade base` drops every table, and after Phase 1 the
working database holds the symbol master and the trading calendar.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.config import get_settings
from app.constants import BRIEF_MAX_ITEMS

BACKEND = Path(__file__).resolve().parents[1]

# Every table in docs/BUILD_SPEC.md §5, §6, §7, §9, §12 and §20, including the
# five the build plan names explicitly as [R2] additions.
EXPECTED_TABLES = {
    "announcements",
    "baselines",
    "brief_cursor_states",
    "candidates",
    "corporate_actions",
    "corporate_action_notices",
    "daily_bars",
    "delivery_stats",
    "delivery_baselines",
    "digest_deliveries",
    "filing_summaries",
    "index_bars",
    "index_snapshots_0930",
    "ingest_quarantine",
    "ingest_runs",
    "instruments",
    "market_model_parameters",
    "market_extremes_adv",
    "read_cursors",
    "signal_events",
    "signal_feedback",
    "symbol_adjustment_factors",
    "symbol_aliases",
    "symbol_liquidity_state",
    "symbol_master_snapshots",
    "trading_calendar",
    "turnover_baselines",
    "users",
    "v_adjusted_bars",
    "watchlist_items",
    "watchlists",
}


def _engine():
    try:
        url = _ensure_scratch_database()
    except Exception as exc:  # noqa: BLE001 — any connection failure is a skip
        pytest.skip(f"postgres unreachable ({type(exc).__name__}); run `make up`")
    return sa.create_engine(url, connect_args={"connect_timeout": 5})


def _ensure_scratch_database() -> str:
    """Create the throwaway database these tests run against, and return its URL.

    Why not the configured database. `downgrade base` drops every table, so
    running this file against the working database destroys whatever has been
    loaded into it — after Phase 1 that is the symbol master and the trading
    calendar, and `make calendar && pytest` would leave an empty calendar
    behind. That is exactly the "discovered at the worst possible moment"
    failure this file's own docstring is about, so the round trip gets its own
    database and touches nothing else.
    """
    configured = sa.engine.make_url(get_settings().database_url)
    scratch = configured.set(database=f"{configured.database}_migrationtest")
    # CREATE DATABASE cannot run inside a transaction, hence AUTOCOMMIT, and it
    # cannot run from the database being created, hence the maintenance one.
    maintenance = sa.create_engine(
        configured.set(database="postgres"), isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )
    with maintenance.connect() as conn:
        exists = conn.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": scratch.database},
        ).first()
        if not exists:
            conn.execute(sa.text(f'CREATE DATABASE "{scratch.database}"'))
    maintenance.dispose()
    return scratch.render_as_string(hide_password=False)


def _alembic(*args: str) -> None:
    # The scratch URL reaches alembic through the environment, which
    # `app.config` reads ahead of `.env`, so the subprocess migrates the
    # throwaway database rather than the configured one.
    env = {**os.environ, "DATABASE_URL": _ensure_scratch_database()}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
    )


def _tables(engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name <> 'alembic_version'"
            )
        )
        return {r[0] for r in rows}


@pytest.fixture(scope="module")
def engine():
    return _engine()


def test_upgrade_head_creates_every_specified_table(engine):
    _alembic("upgrade", "head")
    assert _tables(engine) == EXPECTED_TABLES


def test_downgrade_base_removes_everything(engine):
    _alembic("upgrade", "head")
    _alembic("downgrade", "base")
    assert _tables(engine) == set()


def test_round_trip_is_repeatable(engine):
    """A downgrade that orphans an index or a constraint would make the second
    upgrade fail here rather than in front of the jury."""
    for _ in range(2):
        _alembic("upgrade", "head")
        _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    assert _tables(engine) == EXPECTED_TABLES


def test_daily_bars_primary_key_is_symbol_and_date(engine):
    """§6.2, stated twice in the specification because it is easy to get wrong.

    Adding `series` to the key would PERMIT two rows for one symbol-date rather
    than prevent them.
    """
    _alembic("upgrade", "head")
    with engine.connect() as conn:
        cols = conn.execute(
            sa.text(
                "SELECT a.attname FROM pg_constraint c "
                "JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE "
                "JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum "
                "WHERE c.conrelid='daily_bars'::regclass AND c.contype='p' "
                "ORDER BY k.ord"
            )
        ).scalars().all()
    assert cols == ["symbol", "date"]


def test_every_timestamp_column_is_timezone_aware(engine):
    """§4.3: compute in UTC, display in Asia/Kolkata. A naive column would let a
    19:00 IST announcement land on the previous UTC day."""
    _alembic("upgrade", "head")
    with engine.connect() as conn:
        naive = conn.execute(
            sa.text(
                "SELECT table_name || '.' || column_name "
                "FROM information_schema.columns "
                "WHERE table_schema='public' "
                "AND data_type='timestamp without time zone'"
            )
        ).scalars().all()
    assert naive == []


def test_provenance_columns_are_not_nullable(engine):
    """R4 / N2. Every ingested fact carries source and ingested_at; every
    derived row carries computed_at. Enforced, not merely intended."""
    _alembic("upgrade", "head")
    ingested = [
        "announcements",
        "corporate_actions",
        "daily_bars",
        "delivery_stats",
        "index_bars",
        "index_snapshots_0930",
    ]
    with engine.connect() as conn:
        for table in ingested:
            for column in ("source", "ingested_at"):
                nullable = conn.execute(
                    sa.text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name=:t "
                        "AND column_name=:c"
                    ),
                    {"t": table, "c": column},
                ).scalar()
                assert nullable == "NO", f"{table}.{column} is nullable"
        for table in ("baselines", "signal_events"):
            nullable = conn.execute(
                sa.text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=:t "
                    "AND column_name='computed_at'"
                ),
                {"t": table},
            ).scalar()
            assert nullable == "NO", f"{table}.computed_at is nullable"


def test_bar_validators_reject_impossible_ohlc(engine):
    """§6.2 rule 4, enforced by the database as well as the loader."""
    _alembic("upgrade", "head")
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM daily_bars WHERE symbol='__TEST__'"))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO daily_bars"
                    "(symbol,date,open,high,low,close,source,ingested_at) "
                    "VALUES ('__TEST__','2026-09-04',100,90,95,98,'TEST',NOW())"
                )
            )


def test_delivery_cannot_exceed_traded(engine):
    _alembic("upgrade", "head")
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO delivery_stats"
                    "(symbol,date,traded_qty,deliverable_qty,source,ingested_at) "
                    "VALUES ('__TEST__','2026-09-04',100,200,'TEST',NOW())"
                )
            )


def test_brief_cap_is_enforced_by_the_database(engine):
    """N3: rendering more than BRIEF_MAX_ITEMS scored items is a P0 bug. The
    database refuses to record a delivery that broke the cap, so a violation
    cannot pass silently even if the ranker regresses."""
    _alembic("upgrade", "head")
    with engine.begin() as conn:
        user_id = conn.execute(
            sa.text(
                "INSERT INTO users(display_name) VALUES ('__TEST__') RETURNING id"
            )
        ).scalar()

    def deliver(surfaced: int) -> None:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO digest_deliveries(user_id,delivered_at,candidates,"
                    "suppressed_corporate_action,rolled_up_market_wide,"
                    "rolled_up_sector_wide,suppressed_liquidity,ranked,surfaced,"
                    "quiet_count) "
                    "VALUES (:u,NOW(),100,0,0,0,0,20,:s,0)"
                ),
                {"u": user_id, "s": surfaced},
            )

    deliver(BRIEF_MAX_ITEMS)
    with pytest.raises(sa.exc.IntegrityError):
        deliver(BRIEF_MAX_ITEMS + 1)

    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM users WHERE id=:u"), {"u": user_id})
