"""`make seed` — BUILD_PLAN Task 14.2.

Loads cached NSE files and runs the full pipeline with no network. Every step
below passes ``--from-cache-only`` (or its Python equivalent) and reads only
from ``data/cache/`` and the database — nothing here makes an HTTP request.

Order matters: symbols and the calendar are reference data everything else
joins against; bhavcopy/delivery/index EOD populate `daily_bars` /
`delivery_stats` / `index_bars`; corporate actions and their verification
need `daily_bars` to check ex-date price gaps against; the 09:30 snapshot
falls back to the cached index open when no live/broker provider is given;
and the batch pipeline (adjustment factors, baselines, candidates) needs
everything above it already in the database.

    make seed
    python backend/scripts/seed.py
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.ingest.calendar import earliest_cached_session  # noqa: E402


def log(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def run_module(module: str, *args: str) -> None:
    log(f"python -m {module} {' '.join(args)}")
    result = subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=REPO_ROOT / "backend",
        env={"PYTHONPATH": str(REPO_ROOT / "backend")},
    )
    if result.returncode != 0:
        raise SystemExit(f"{module} failed with exit code {result.returncode}")


def cached_date_range() -> tuple[date, date]:
    cache_root = Path(get_settings().cache_root)
    start = earliest_cached_session(cache_root)
    if start is None:
        raise SystemExit(
            "no cached bhavcopy found under data/cache/bhavcopy — "
            "run `make backfill` once with network before `make seed`"
        )
    bhavcopy_dir = cache_root / "bhavcopy"
    end = max(
        date.fromisoformat(child.name)
        for child in bhavcopy_dir.iterdir()
        if child.is_dir() and any(child.glob("*.zip"))
    )
    return start, end


def main() -> int:
    start, end = cached_date_range()
    log(f"seeding from the cache: {start} .. {end}")

    run_module("app.ingest.symbol_master", "--from-cache-only")
    run_module("app.ingest.calendar", "--from-cache-only")
    run_module("app.ingest.corporate_actions", "--from-cache-only")
    run_module(
        "app.ingest.announcement_ingest",
        "--from", start.isoformat(),
        "--to", end.isoformat(),
        "--from-cache-only",
    )
    run_module(
        "app.ingest.backfill",
        "--from", start.isoformat(),
        "--to", end.isoformat(),
        "--from-cache-only",
    )
    run_module("app.ingest.ca_verify", "--history")
    run_module("app.ingest.ca_infer", "--history")

    log("09:30 index snapshots (ESTIMATED_FROM_OPEN, from cached index EOD)")
    import sqlalchemy as sa

    from app.ingest.index_snapshot import backfill_index_snapshots_0930

    engine = get_engine()
    with engine.connect() as conn:
        dates = conn.execute(
            sa.text("SELECT DISTINCT date FROM daily_bars ORDER BY date")
        ).scalars().all()
    count = backfill_index_snapshots_0930(dates, engine=engine)
    print(f"{count} index snapshot rows written")

    log("batch pipeline: adjustment factors, baselines, candidates")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "backend" / "scripts" / "run_full_pipeline.py")],
        cwd=REPO_ROOT / "backend",
    )
    if result.returncode != 0:
        raise SystemExit(f"run_full_pipeline.py failed with exit code {result.returncode}")

    log("seed complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
