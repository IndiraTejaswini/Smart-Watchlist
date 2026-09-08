"""`ingest_runs` bookkeeping — docs/BUILD_SPEC.md §6.2 rules 2 and 3.

Every ingest module needs the same three operations: open a run row
pessimistically, close it with a verdict, and ask whether this exact input was
already loaded successfully. `symbol_master.py`, `calendar.py` and
`corporate_actions.py` each carried an identical private copy of this before
`bhavcopy.py` needed a fourth — the duplication was a sign the contract
belonged in one place, not four.

Every function takes `source` explicitly rather than reading a module global,
so a caller cannot accidentally record one module's run under another's name.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa


def start_run(conn: sa.Connection, *, source: str, target_date: date, file_hash: str) -> int:
    """Open an `ingest_runs` row (§6.2 rule 2), `FAILED` until it is not.

    Opened pessimistically so that a crash between here and `finish_run` leaves
    a row that says the run failed, rather than no row at all — R5, fail
    visibly.
    """
    return int(
        conn.execute(
            sa.text(
                "INSERT INTO ingest_runs (source, target_date, status, file_hash, started_at) "
                "VALUES (:source, :target_date, 'FAILED', :file_hash, NOW()) RETURNING id"
            ),
            {"source": source, "target_date": target_date, "file_hash": file_hash},
        ).scalar_one()
    )


def finish_run(
    conn: sa.Connection, run_id: int, *, status: str, rows: int, error: str | None = None
) -> None:
    conn.execute(
        sa.text(
            "UPDATE ingest_runs SET status = :status, rows = :rows, error = :error, "
            "finished_at = NOW() WHERE id = :id"
        ),
        {"status": status, "rows": rows, "error": error, "id": run_id},
    )


def already_ingested(
    conn: sa.Connection, *, source: str, target_date: date, file_hash: str
) -> bool:
    """§6.2 rule 3: this exact input set already loaded successfully for this
    source and date. A matching hash short-circuits parsing entirely."""
    return bool(
        conn.execute(
            sa.text(
                "SELECT 1 FROM ingest_runs WHERE source = :source AND target_date = :d "
                "AND file_hash = :h AND status = 'OK' LIMIT 1"
            ),
            {"source": source, "d": target_date, "h": file_hash},
        ).first()
    )
