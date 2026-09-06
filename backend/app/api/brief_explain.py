"""Transparent digest-item explainability endpoint."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException

from app.analytics.attribution import AttributionCategory, AttributionResult
from app.analytics.candidates import Candidate, SignalFamily
from app.analytics.explain import build_score_audit, trace_decision_path
from app.analytics.mpm import MPMResult
from app.analytics.ranker import PersonalContext
from app.db import get_engine
from app.schemas.explain import ExplainBriefItemResponse, RankContext

router = APIRouter(prefix="/api/brief", tags=["brief"])


def connection() -> Iterator[sa.Connection]:
    with get_engine().connect() as conn:
        yield conn


Connection = Annotated[sa.Connection, Depends(connection)]


def _candidate(row: Any) -> Candidate:
    families = frozenset(
        SignalFamily(value)
        for value in (row.get("signal_families") or [row["primary_signal"]])
    )
    return Candidate(
        symbol=str(row["symbol"]),
        date=row["date"],
        signal_families=families,
        primary_signal=SignalFamily(str(row["primary_signal"])),
        sar=float(row["sar"]),
        turnover_z=None if row.get("turnover_z") is None else float(row["turnover_z"]),
        delivery_z=None if row.get("delivery_z") is None else float(row["delivery_z"]),
        material_announcements_count=int(
            row.get("material_announcements_count", row.get("has_material_filing", 0))
        ),
        inputs_hash=str(row.get("inputs_hash", "")),
    )


@router.get("/explain/{item_id}", response_model=ExplainBriefItemResponse)
def explain_brief_item(item_id: str, conn: Connection) -> ExplainBriefItemResponse:
    row = conn.execute(
        sa.text("SELECT * FROM candidates WHERE symbol = :item_id ORDER BY date DESC LIMIT 1"),
        {"item_id": item_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Brief item not found")

    candidate = _candidate(row)
    from app.timeutil import TradingCalendar

    calendar = TradingCalendar.from_rows(
        [
            {
                "calendar_date": candidate.date,
                "is_trading_day": True,
                "session_type": "REGULAR",
            }
        ]
    )
    context = PersonalContext()
    base, decay, personal, final_score = build_score_audit(
        candidate, candidate.date, context, calendar
    )
    mpm = MPMResult(False, False, 0.0, 0.0, 0.0, 0.0, 0.0, False)
    attribution = AttributionResult(
        symbol=candidate.symbol,
        date=candidate.date,
        category=AttributionCategory.IDIOSYNCRATIC,
        market_ratio=0.0,
        sar=candidate.sar,
        beta=0.0,
        is_rollup_eligible=False,
        reason="No persisted attribution context was available.",
    )
    return ExplainBriefItemResponse(
        signal_event_id=item_id,
        session_date=str(candidate.date),
        family=candidate.primary_signal.value,
        classification=candidate.primary_category or "UNEXPLAINED",
        rank=1,
        item_id=item_id,
        brief_id=str(row.get("brief_id", "")),
        symbol=candidate.symbol,
        inputs_hash=candidate.inputs_hash,
        data_status="FINAL",
        completeness_set=[],
        decision_path=trace_decision_path(candidate, None, mpm, attribution),
        base_score=base,
        decay=decay,
        personal=personal,
        final_score=final_score,
        rank_context=RankContext(
            rank=1,
            total_brief_items=1,
            delta_to_rank_above=None,
            symbol_above=None,
            delta_to_rank_below=None,
            symbol_below=None,
            why_ranked_here="This is the only persisted item available for comparison.",
        ),
        completeness=[],
        sections=[
            {
                "title": "Base score",
                "rows": [
                    {"label": "SAR", "value": base.sar_raw, "format": "number"},
                    {
                        "label": "Turnover z",
                        "value": base.turnover_z_raw or 0.0,
                        "format": "number",
                    },
                    {
                        "label": "Delivery z",
                        "value": base.delivery_z_raw or 0.0,
                        "format": "number",
                    },
                ],
            },
            {
                "title": "Final score",
                "rows": [
                    {"label": "Score", "value": final_score, "format": "number"},
                ],
            },
        ],
    )
