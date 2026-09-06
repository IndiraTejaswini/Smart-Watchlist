"""Post-close candidate restatement workflow."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from app.analytics.candidates import Candidate


def recompute_eod_candidates(
    db: Any, trading_date: date, bhavcopy_records: list[Any]
) -> list[Candidate]:
    """Supersede active provisional candidates with immutable final revisions.

    The database transaction is owned by the caller; all writes happen through
    the supplied connection/session so ingestion can commit atomically.
    """
    delivery_by_symbol = {
        str(getattr(row, "symbol", row.get("symbol"))): getattr(
            row, "delivery_z", row.get("delivery_z")
        )
        for row in bhavcopy_records
    }
    rows = db.execute(
        sa.text(
            "SELECT * FROM candidates "
            "WHERE date = :trading_date AND status = 'PROVISIONAL' "
            "AND superseded_by_id IS NULL FOR UPDATE"
        ),
        {"trading_date": trading_date},
    ).mappings()
    finals: list[Candidate] = []
    for row in rows:
        old_id = str(row.get("id", f"{row['date']}:{row['symbol']}"))
        final_id = str(uuid4())
        delivery_z = delivery_by_symbol.get(str(row["symbol"]))
        final = Candidate(
            symbol=str(row["symbol"]),
            date=row["date"],
            signal_families=frozenset(row.get("signal_families", ())),
            primary_signal=row["primary_signal"],
            sar=float(row["sar"]),
            turnover_z=float(row["turnover_z"]) if row.get("turnover_z") is not None else None,
            delivery_z=float(delivery_z) if delivery_z is not None else None,
            material_announcements_count=int(row.get("material_announcements_count", 0)),
            metadata=dict(row.get("metadata", {})),
            inputs_hash=str(row.get("inputs_hash", "")),
            revision=int(row.get("revision", 1)) + 1,
            status="FINAL",
            was_restated=True,
            id=final_id,
        )
        db.execute(
            sa.text(
                "UPDATE candidates SET superseded_by_id = :final_id "
                "WHERE id = :old_id"
            ),
            {"final_id": final_id, "old_id": old_id},
        )
        db.execute(
            sa.text(
                "INSERT INTO candidates "
                "(id, date, symbol, revision, status, was_restated, delivery_z, "
                "superseded_by_id) VALUES (:id, :date, :symbol, :revision, "
                ":status, :was_restated, :delivery_z, NULL)"
            ),
            {
                "id": final_id,
                "date": trading_date,
                "symbol": final.symbol,
                "revision": final.revision,
                "status": final.status,
                "was_restated": final.was_restated,
                "delivery_z": final.delivery_z,
            },
        )
        finals.append(final)
    return finals
