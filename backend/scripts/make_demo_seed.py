"""Build a trimmed demo seed dump that fits Neon's free 0.5 GB ceiling.

The full seed (`seed.dump`, ~98 MB compressed, ~1.1 GB restored) covers the
whole ~2,500-instrument reference universe over the full backfilled history.
Neon's free tier does not have room for that. This script produces
`seed_demo.dump`: the same schema, but data trimmed to

  - the eval universe (every symbol that ever produced a row in `candidates`,
    i.e. exactly the ~200 symbols `pick_universe()` selected — the ground
    truth of "what the pipeline actually scored"), plus every symbol on any
    seeded watchlist, so a demo user's own list never 404s a symbol lookup;
  - roughly the last N months of history (default 8 — BETA_WINDOW_DAYS (120)
    + BETA_GAP_DAYS (5) is ~125 calendar days of hard floor; 8 months leaves
    wide margin for weekends/holidays without tuning this per run);
  - `instruments`, `trading_calendar`, `index_bars`, `index_snapshots_0930`
    in full — small, and every symbol-scoped table joins against them;
  - the demo user's own watchlists, watchlist items and cursors, filtered by
    user_id rather than assumed to be the only rows.

Everything else (the other ~2,300 instruments' bars/baselines/announcements,
any other symbol's corporate actions) is dropped outright, not sampled.

Mechanism: build the trimmed dataset into a scratch database on the same
Postgres server (`swl_demo_build` by default), `alembic upgrade head` it to
get the exact current schema including views, stream-copy the filtered rows
table by table (SELECT on the source connection, COPY FROM STDIN on the
scratch connection — the two live in different databases, so a plain
cross-database INSERT isn't available), `pg_dump` the result, then drop the
scratch database.

    python backend/scripts/make_demo_seed.py
    python backend/scripts/make_demo_seed.py --verify   # also restore-and-check
    python backend/scripts/make_demo_seed.py --months 6 --out seed_demo.dump

Re-run this after any pipeline change — it is not a one-off set of manual SQL
statements, and the eval universe it captures is only as current as the last
`make pipeline` / `make seed` run against the source database.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.types.json import Jsonb

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import get_settings  # noqa: E402

DEMO_USER_ID = "demo_trader"
SCRATCH_DB_NAME = "swl_demo_build"
DEFAULT_OUT = REPO_ROOT / "seed_demo.dump"
DEFAULT_MONTHS = 8


def log(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


# ─── Connection plumbing ─────────────────────────────────────────────────────


def _server_dsn_and_dbname(database_url: str) -> tuple[str, str]:
    """Split a SQLAlchemy-style URL into a plain libpq DSN plus the db name.

    `psycopg.connect()` and `pg_dump`/`createdb` want a plain
    `postgresql://` URL (or DSN), not SQLAlchemy's `postgresql+psycopg://`.
    """
    parts = urlsplit(database_url)
    scheme = parts.scheme.split("+")[0]
    dbname = parts.path.lstrip("/")
    server_url = urlunsplit((scheme, parts.netloc, "/postgres", parts.query, ""))
    return server_url, dbname


def months_before(d: date, months: int) -> date:
    """Calendar-month subtraction without a dateutil dependency."""
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


# ─── Table plan ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]
    # Built against bound params: universe (tuple[str]), start_date (date),
    # demo_user (str). Empty where clause means "copy every row".
    where_sql: str = ""
    order_by: str = ""


# Reference data everything else joins against — copied whole because it is
# small, not because it is exempt from trimming in spirit.
REFERENCE_TABLES = (
    TableSpec("instruments", (
        "instrument_id", "symbol", "isin", "name", "series", "sector",
        "sector_source", "industry", "face_value", "listing_date",
        "is_active", "primary_venue", "has_derivatives",
    )),
    TableSpec("symbol_aliases", (
        "old_symbol", "instrument_id", "effective_date", "note",
    )),
    TableSpec("trading_calendar", (
        "calendar_date", "is_trading_day", "pre_open_start", "pre_open_end",
        "regular_open", "regular_close", "post_close_end", "session_type",
        "notes",
    )),
    TableSpec("index_bars", (
        "index_symbol", "date", "open", "high", "low", "close", "prev_close",
        "source", "ingested_at",
    )),
    TableSpec("index_snapshots_0930", (
        "index_symbol", "trading_date", "value", "captured_at", "source",
        "ingested_at", "quality_flag",
    )),
)

# Symbol- and date-scoped facts: WHERE symbol = ANY(:universe) AND date >= :start_date
UNIVERSE_DATE_TABLES = (
    TableSpec("daily_bars", (
        "symbol", "date", "open", "high", "low", "close", "prev_close",
        "vwap", "volume", "turnover", "trades", "upper_band", "lower_band",
        "series", "source", "ingested_at",
    )),
    TableSpec("delivery_stats", (
        "symbol", "date", "traded_qty", "deliverable_qty", "delivery_pct",
        "series", "source", "ingested_at",
    )),
    TableSpec("symbol_adjustment_factors", (
        "symbol", "date", "cum_price_factor", "cum_tr_factor",
        "cum_vol_factor", "updated_at",
    )),
    TableSpec("turnover_baselines", (
        "date", "symbol", "mean_log_turnover", "std_log_turnover", "n_obs",
        "quality_flag", "created_at",
    )),
    TableSpec("delivery_baselines", (
        "date", "symbol", "raw_delivery_pct", "logit_delivery",
        "mean_logit_20d", "std_logit_20d", "delivery_z_score", "n_obs",
        "quality_flag", "created_at",
    )),
    TableSpec("market_model_parameters", (
        "date", "symbol", "alpha", "beta", "r2", "resid_sd", "n_obs",
        "quality_flag",
    )),
    TableSpec("market_extremes_adv", (
        "date", "symbol", "high_52w", "low_52w", "distance_to_52w_high_pct",
        "distance_to_52w_low_pct", "adv_20d", "n_obs_52w", "created_at",
    )),
    TableSpec("baselines", (
        "symbol", "date", "alpha", "beta", "resid_sd", "n_obs", "r2",
        "quality", "mean_log_turnover", "sd_log_turnover",
        "mean_delivery_logit", "sd_delivery_logit", "high_52w", "low_52w",
        "adv_20d", "computed_at",
    )),
    TableSpec("symbol_liquidity_state", (
        "symbol", "date", "is_liquid", "adv_20d", "last_state_change_date",
        "updated_at",
    )),
    TableSpec("candidates", (
        "date", "symbol", "signal_families", "primary_signal", "sar",
        "turnover_z", "delivery_z", "scar_3d", "has_material_filing",
        "inputs_hash", "created_at", "linked_announcement_ids",
        "primary_category", "is_explained", "id", "revision", "status",
        "was_restated", "superseded_by_id", "sector",
    )),
)

# Symbol-scoped, own date column named differently, or small enough that a
# date floor barely matters — filtered by symbol only.
UNIVERSE_ONLY_TABLES = (
    TableSpec("corporate_actions", (
        "id", "symbol", "ex_date", "record_date", "action_type",
        "ratio_text", "purpose_raw", "price_factor", "tr_factor",
        "verification", "observed_gap", "source", "ingested_at",
    )),
    TableSpec("corporate_action_notices", (
        "id", "symbol", "ex_date", "cum_date", "action_type",
        "as_traded_cum_close", "adjusted_prev_close", "adjustment_factor",
        "ratio_or_amount", "headline", "detail_text", "source_url",
        "created_at",
    )),
)

# announcements uses filed_at, not date — its own clause.
ANNOUNCEMENTS_TABLE = TableSpec("announcements", (
    "id", "symbol", "filed_at", "subject", "category", "schedule_iii",
    "attachment_url", "raw_json", "content_hash", "source", "ingested_at",
    "para_ref",
))

# Empty or near-empty operational tables. Copied in full: trimming them buys
# nothing (a handful of KB) and risks missing a column the app reads. Signal
# events referencing a `symbol` column that has drifted out of the trimmed
# universe would be a dangling reference with no FK to catch it, but every
# one of these tables is empty on the source database at the time of
# writing, so `date`/`symbol`-scoping them is unnecessary in practice.
SMALL_FULL_TABLES = (
    TableSpec("users", ("id", "email", "display_name", "created_at")),
    TableSpec("ingest_runs", (
        "id", "source", "target_date", "status", "rows", "file_hash",
        "started_at", "finished_at", "error",
    )),
    TableSpec("ingest_quarantine", (
        "id", "ingest_run_id", "source_file", "raw_payload",
        "rejection_reason", "created_at",
    )),
    TableSpec("digest_deliveries", (
        "id", "user_id", "delivered_at", "cursor_ts", "candidates",
        "suppressed_corporate_action", "rolled_up_market_wide",
        "rolled_up_sector_wide", "suppressed_liquidity", "ranked",
        "surfaced", "quiet_count", "signal_event_ids", "brief_id",
        "as_of_ts", "cursor_ack_ts", "n_scored_items", "n_corporate_actions",
        "n_market_rollups", "n_sector_rollups", "n_total_delivered",
        "n_candidates_evaluated", "n_candidates_delivered",
        "n_suppressed_illiquidity", "n_suppressed_refractory",
        "n_suppressed_corporate_action", "n_suppressed_rollup",
        "n_suppressed_diversity", "n_truncated_hard_cap", "inputs_hash",
    )),
    TableSpec("filing_summaries", (
        "id", "brief_id", "symbol", "announcement_id", "model_version",
        "prompt_text", "raw_output", "is_valid", "validation_failure_reason",
        "sanitized_sentence", "created_at",
    )),
    TableSpec("signal_feedback", (
        "id", "signal_event_id", "user_id", "verdict", "note", "created_at",
    )),
    TableSpec("symbol_master_snapshots", (
        "snapshot_date", "instrument_id", "payload",
    )),
    TableSpec("signal_events", (
        "id", "symbol", "as_of", "trading_date", "window_start",
        "window_end", "family", "classification", "sign", "pct_move", "ar",
        "sar", "car", "scar", "turnover_z", "delivery_z", "delivery_pct",
        "mpm_triggered", "mpm_base_threshold", "mpm_effective_threshold",
        "band_hit", "linked_announcement_ids", "explained_by_ca_id",
        "score_base", "completeness", "provisional", "revision",
        "superseded_by", "inputs_hash", "computed_at",
    )),
)

# The demo user's own rows — filtered by user_id, not assumed to be the only
# ones in the source database.
DEMO_USER_TABLES = (
    TableSpec("watchlists", ("id", "user_id", "name", "created_at", "version", "updated_at")),
    TableSpec("read_cursors", (
        "user_id", "feed_id", "last_read_seq", "last_read_at", "updated_at",
    )),
    TableSpec("brief_cursor_states", (
        "user_id", "feed_id", "seen_through_ts", "acknowledged_through_ts", "updated_at",
    )),
)
WATCHLIST_ITEMS_TABLE = TableSpec("watchlist_items", (
    "id", "watchlist_id", "symbol", "position", "created_at",
))


# ─── Copy mechanics ──────────────────────────────────────────────────────────


def _fetch_column_types(src_conn: psycopg.Connection, table: str, columns: tuple[str, ...]) -> None:
    # Validates every declared column actually exists before we start
    # streaming — a typo here should fail fast, not mid-COPY on table N of 30.
    with src_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        real = {row[0] for row in cur.fetchall()}
    missing = [c for c in columns if c not in real]
    if missing:
        raise SystemExit(f"{table}: TableSpec lists unknown columns {missing}")


def copy_table(
    src_conn: psycopg.Connection,
    dst_conn: psycopg.Connection,
    spec: TableSpec,
    params: dict,
) -> int:
    _fetch_column_types(src_conn, spec.name, spec.columns)
    col_list = ", ".join(spec.columns)
    select_sql = f"SELECT {col_list} FROM {spec.name}"
    if spec.where_sql:
        select_sql += f" WHERE {spec.where_sql}"

    row_count = 0
    with src_conn.cursor(name=f"seed_export_{spec.name}") as src_cur:
        src_cur.itersize = 5000
        src_cur.execute(select_sql, params)
        with dst_conn.cursor() as dst_cur:
            copy_sql = f"COPY {spec.name} ({col_list}) FROM STDIN"
            with dst_cur.copy(copy_sql) as copy:
                for row in src_cur:
                    # psycopg reads jsonb columns back as plain dict/list, but
                    # the COPY writer needs an explicit Jsonb() wrapper to
                    # know how to serialise one — announcements.raw_json is
                    # the one column this affects.
                    row = tuple(
                        Jsonb(value) if isinstance(value, dict) else value for value in row
                    )
                    copy.write_row(row)
                    row_count += 1
    dst_conn.commit()
    return row_count


def reset_sequences(dst_conn: psycopg.Connection) -> None:
    """After COPYing explicit id values, point every serial/identity column's
    sequence past the max id it just received — otherwise the first insert
    the running app makes collides with a copied row."""
    with dst_conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname AS table_name, a.attname AS column_name,
                   pg_get_serial_sequence(c.relname, a.attname) AS seq
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND a.attnum > 0 AND NOT a.attisdropped
              AND pg_get_serial_sequence(c.relname, a.attname) IS NOT NULL
            """
        )
        rows = cur.fetchall()
        for table_name, column_name, seq in rows:
            cur.execute(
                f'SELECT setval(%s, COALESCE((SELECT MAX("{column_name}") '
                f'FROM "{table_name}"), 1), '
                f'(SELECT MAX("{column_name}") FROM "{table_name}") IS NOT NULL)',
                (seq,),
            )
    dst_conn.commit()


# ─── Orchestration ───────────────────────────────────────────────────────────


def resolve_universe(src_conn: psycopg.Connection) -> tuple[str, ...]:
    with src_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT symbol FROM candidates")
        eval_universe = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT DISTINCT symbol FROM watchlist_items")
        watchlist_symbols = {row[0] for row in cur.fetchall()}
    universe = tuple(sorted(eval_universe | watchlist_symbols))
    log(
        f"universe: {len(eval_universe)} eval symbols + "
        f"{len(watchlist_symbols - eval_universe)} extra watchlist symbols "
        f"= {len(universe)} total"
    )
    return universe


def resolve_start_date(src_conn: psycopg.Connection, months: int) -> date:
    with src_conn.cursor() as cur:
        cur.execute("SELECT MAX(date) FROM daily_bars")
        (last_date,) = cur.fetchone()
    if last_date is None:
        raise SystemExit("daily_bars is empty on the source database — run `make seed` first")
    start = months_before(last_date, months)
    log(f"history window: {start} .. {last_date} ({months} months)")
    return start


def create_scratch_database(server_dsn: str, scratch_name: str) -> None:
    log(f"(re)creating scratch database {scratch_name!r}")
    with psycopg.connect(server_dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{scratch_name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{scratch_name}"')


def drop_scratch_database(server_dsn: str, scratch_name: str) -> None:
    with psycopg.connect(server_dsn, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{scratch_name}" WITH (FORCE)')


def migrate_scratch_database(scratch_url: str) -> None:
    log("alembic upgrade head (scratch)")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT / "backend",
        env={
            **_subprocess_env(),
            "DATABASE_URL": scratch_url,
        },
    )
    if result.returncode != 0:
        raise SystemExit("alembic upgrade head failed against the scratch database")


def _subprocess_env() -> dict:
    import os

    return dict(os.environ)


def build_demo_dataset(source_url: str, scratch_name: str, months: int) -> str:
    server_dsn, _ = _server_dsn_and_dbname(source_url)
    scratch_url = server_dsn.rsplit("/", 1)[0] + f"/{scratch_name}"

    create_scratch_database(server_dsn, scratch_name)
    migrate_scratch_database(scratch_url.replace("postgresql://", "postgresql+psycopg://"))

    log("connecting source and scratch databases")
    with psycopg.connect(source_url) as src, psycopg.connect(scratch_url) as dst:
        universe = resolve_universe(src)
        start_date = resolve_start_date(src, months)
        params = {"universe": list(universe), "start_date": start_date, "demo_user": DEMO_USER_ID}

        specs_in_order: list[tuple[TableSpec, str, dict]] = []
        for spec in REFERENCE_TABLES:
            specs_in_order.append((spec, "", params))
        for spec in DEMO_USER_TABLES[:1]:  # watchlists first — watchlist_items FKs to it
            specs_in_order.append((spec, "user_id = %(demo_user)s", params))
        specs_in_order.append((
            WATCHLIST_ITEMS_TABLE,
            "watchlist_id IN (SELECT id FROM watchlists WHERE user_id = %(demo_user)s)",
            params,
        ))
        for spec in DEMO_USER_TABLES[1:]:
            specs_in_order.append((spec, "user_id = %(demo_user)s", params))
        for spec in UNIVERSE_DATE_TABLES:
            specs_in_order.append((
                spec, "symbol = ANY(%(universe)s) AND date >= %(start_date)s", params
            ))
        for spec in UNIVERSE_ONLY_TABLES:
            specs_in_order.append((spec, "symbol = ANY(%(universe)s)", params))
        specs_in_order.append((
            ANNOUNCEMENTS_TABLE,
            "symbol = ANY(%(universe)s) AND filed_at >= %(start_date)s",
            params,
        ))
        for spec in SMALL_FULL_TABLES:
            specs_in_order.append((spec, "", params))

        log("copying tables")
        for spec, where_sql, spec_params in specs_in_order:
            scoped = TableSpec(spec.name, spec.columns, where_sql)
            count = copy_table(src, dst, scoped, spec_params)
            print(f"  {spec.name}: {count} rows")

        log("resetting sequences on the scratch database")
        reset_sequences(dst)

    return scratch_url


def dump_scratch_database(scratch_url: str, out_path: Path) -> None:
    log(f"pg_dump -> {out_path}")
    with out_path.open("wb") as fh:
        result = subprocess.run(
            ["pg_dump", "--no-owner", "--no-acl", "-Fc", scratch_url],
            stdout=fh,
        )
    if result.returncode != 0:
        raise SystemExit("pg_dump failed")
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"  wrote {out_path} ({size_mb:.1f} MB compressed)")


def verify_restore(dump_path: Path, server_dsn: str, scratch_name: str) -> int:
    """Restore the dump into a fresh scratch database and report its size."""
    log(f"verify: restoring {dump_path} into {scratch_name!r}")
    create_scratch_database(server_dsn, scratch_name)
    scratch_url = server_dsn.rsplit("/", 1)[0] + f"/{scratch_name}"
    result = subprocess.run(
        ["pg_restore", "--no-owner", "--no-acl", "-d", scratch_url, str(dump_path)],
    )
    if result.returncode != 0:
        raise SystemExit("pg_restore failed")
    with psycopg.connect(scratch_url) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT pg_database_size(%s)", (scratch_name,))
            (size_bytes,) = cur.fetchone()
    size_mb = size_bytes / 1024 / 1024
    print(f"  pg_database_size({scratch_name}) = {size_mb:.1f} MB")
    return size_bytes


def run_demo_assertion(scratch_url: str) -> None:
    """The same check as `test_demo_end_to_end.py`, against the restored
    scratch database, so a bad trim is caught right here rather than at the
    next `pytest` run."""
    log("running the end-to-end demo assertion against the restored seed")
    env = {**_subprocess_env(), "DATABASE_URL": scratch_url.replace(
        "postgresql://", "postgresql+psycopg://"
    )}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_demo_end_to_end.py", "-v"],
        cwd=REPO_ROOT / "backend",
        env=env,
    )
    if result.returncode != 0:
        raise SystemExit(
            "the trimmed seed failed the end-to-end demo assertion — "
            "a trimmed seed that produces an empty Brief is worse than no deployment"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=DEFAULT_MONTHS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--scratch-db", default=SCRATCH_DB_NAME)
    parser.add_argument(
        "--verify", action="store_true",
        help="restore the dump into a second scratch db, report its size, and "
             "run the end-to-end demo assertion against it",
    )
    parser.add_argument(
        "--keep-scratch", action="store_true",
        help="don't drop the build scratch database on exit (for inspection)",
    )
    args = parser.parse_args()

    source_url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    server_dsn, _ = _server_dsn_and_dbname(source_url)

    scratch_url = build_demo_dataset(source_url, args.scratch_db, args.months)
    dump_scratch_database(scratch_url, args.out)

    if not args.keep_scratch:
        drop_scratch_database(server_dsn, args.scratch_db)

    if args.verify:
        verify_name = f"{args.scratch_db}_verify"
        verify_restore(args.out, server_dsn, verify_name)
        verify_url = server_dsn.rsplit("/", 1)[0] + f"/{verify_name}"
        run_demo_assertion(verify_url)
        if not args.keep_scratch:
            drop_scratch_database(server_dsn, verify_name)

    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
