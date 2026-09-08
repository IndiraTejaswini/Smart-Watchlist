"""Transparent digest-item explainability endpoint."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException

from app.analytics.attribution import AttributionResult, classify_market_attribution
from app.analytics.candidates import candidate_from_row
from app.analytics.explain import build_score_audit, trace_decision_path
from app.analytics.fact_bundle import FactBundle, MarketModelFact
from app.analytics.mpm import MPMResult, evaluate_mpm_gate
from app.analytics.ranker import PersonalContext
from app.constants import MPM_INDEX_ADJUST_MIN_PCT
from app.db import get_engine
from app.ingest.calendar import load_trading_calendar
from app.schemas.explain import ExplainBriefItemResponse, RankContext

router = APIRouter(prefix="/api/brief", tags=["brief"])


def connection() -> Iterator[sa.Connection]:
    with get_engine().connect() as conn:
        yield conn


Connection = Annotated[sa.Connection, Depends(connection)]

_candidate = candidate_from_row


def _real_mpm(conn: sa.Connection, symbol: str, day) -> MPMResult:
    """Recompute the real MPM gate for this candidate's day from daily_bars."""
    row = conn.execute(
        sa.text(
            "SELECT high, low, close, prev_close FROM daily_bars "
            "WHERE symbol = :symbol AND date = :date"
        ),
        {"symbol": symbol, "date": day},
    ).mappings().first()
    if row is None or not row["prev_close"]:
        return MPMResult(False, False, 0.0, 0.0, 0.0, 0.0, 0.0, False)
    index_rows = list(
        conn.execute(
            sa.text(
                "SELECT date, close FROM index_bars WHERE index_symbol = 'Nifty 50' "
                "AND date <= :date ORDER BY date DESC LIMIT 2"
            ),
            {"date": day},
        ).mappings()
    )
    index_return = Decimal("0")
    if len(index_rows) == 2 and index_rows[1]["close"]:
        index_return = (
            Decimal(str(index_rows[0]["close"])) - Decimal(str(index_rows[1]["close"]))
        ) / Decimal(str(index_rows[1]["close"]))
    try:
        return evaluate_mpm_gate(
            Decimal(str(row["prev_close"])),
            Decimal(str(row["high"])),
            Decimal(str(row["low"])),
            Decimal(str(row["close"])),
            index_return,
        )
    except ValueError:
        return MPMResult(False, False, 0.0, 0.0, 0.0, 0.0, 0.0, False)


def _real_attribution(conn: sa.Connection, candidate) -> AttributionResult:
    model_row = conn.execute(
        sa.text(
            "SELECT alpha, beta, resid_sd, quality_flag FROM market_model_parameters "
            "WHERE symbol = :symbol AND date = :date"
        ),
        {"symbol": candidate.symbol, "date": candidate.date},
    ).mappings().first()
    if model_row is None:
        return AttributionResult(
            symbol=candidate.symbol,
            date=candidate.date,
            category="IDIOSYNCRATIC",  # type: ignore[arg-type]
            market_ratio=0.0,
            sar=candidate.sar,
            beta=0.0,
            is_rollup_eligible=False,
            reason="No persisted market-model parameters for this symbol-date.",
        )
    index_rows = list(
        conn.execute(
            sa.text(
                "SELECT date, close FROM index_bars WHERE index_symbol = 'Nifty 50' "
                "AND date <= :date ORDER BY date DESC LIMIT 2"
            ),
            {"date": candidate.date},
        ).mappings()
    )
    bench_ret = Decimal("0")
    if len(index_rows) == 2 and index_rows[1]["close"]:
        bench_ret = (
            Decimal(str(index_rows[0]["close"])) - Decimal(str(index_rows[1]["close"]))
        ) / Decimal(str(index_rows[1]["close"]))
    bundle = FactBundle(
        symbol=candidate.symbol,
        date=candidate.date,
        market_model=MarketModelFact(
            alpha=Decimal(str(model_row["alpha"])),
            beta=Decimal(str(model_row["beta"])),
            r2=None,
            resid_sd=Decimal(str(model_row["resid_sd"])),
            n_obs=0,
            quality_flag=model_row["quality_flag"],
        ),
    )
    return classify_market_attribution(candidate, bundle, bench_ret)


@router.get("/explain/{item_id}", response_model=ExplainBriefItemResponse)
def explain_brief_item(item_id: str, conn: Connection) -> ExplainBriefItemResponse:
    row = conn.execute(
        sa.text("SELECT * FROM candidates WHERE id = :item_id"),
        {"item_id": item_id},
    ).mappings().first()
    if row is None:
        # Fall back to symbol-only lookup for callers still using the old id shape.
        row = conn.execute(
            sa.text(
                "SELECT * FROM candidates WHERE symbol = :item_id ORDER BY date DESC LIMIT 1"
            ),
            {"item_id": item_id},
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Brief item not found")

    candidate = _candidate(dict(row))
    calendar = load_trading_calendar(
        conn, candidate.date - timedelta(days=400), candidate.date
    )
    context = PersonalContext()
    base, decay, personal, final_score = build_score_audit(
        candidate, candidate.date, context, calendar
    )
    mpm = _real_mpm(conn, candidate.symbol, candidate.date)
    attribution = _real_attribution(conn, candidate)

    same_day_rows = list(
        conn.execute(
            sa.text("SELECT symbol, sar FROM candidates WHERE date = :date ORDER BY ABS(sar) DESC"),
            {"date": candidate.date},
        ).mappings()
    )
    symbols_in_order = [r["symbol"] for r in same_day_rows]
    rank = (
        symbols_in_order.index(candidate.symbol) + 1
        if candidate.symbol in symbols_in_order
        else 1
    )
    total = len(symbols_in_order) or 1
    symbol_above = symbols_in_order[rank - 2] if rank >= 2 else None
    symbol_below = symbols_in_order[rank] if rank < total else None

    completeness = []
    if row.get("turnover_z") is not None:
        completeness.append("TURNOVER")
    if row.get("delivery_z") is not None:
        completeness.append("DELIVERY")
    if row.get("scar_3d") is not None:
        completeness.append("MULTI_SESSION")

    return ExplainBriefItemResponse(
        signal_event_id=item_id,
        session_date=str(candidate.date),
        family=candidate.primary_signal.value,
        classification="EXPLAINED" if candidate.is_explained else "UNEXPLAINED",
        rank=rank,
        item_id=item_id,
        brief_id=str(row.get("brief_id", "")),
        symbol=candidate.symbol,
        inputs_hash=candidate.inputs_hash,
        data_status=candidate.status,
        completeness_set=completeness,
        decision_path=trace_decision_path(candidate, None, mpm, attribution),
        base_score=base,
        decay=decay,
        personal=personal,
        final_score=final_score,
        rank_context=RankContext(
            rank=rank,
            total_brief_items=total,
            delta_to_rank_above=None,
            symbol_above=symbol_above,
            delta_to_rank_below=None,
            symbol_below=symbol_below,
            why_ranked_here=(
                f"Ranked by |SAR| among {total} candidates evaluated on {candidate.date}."
            ),
        ),
        completeness=completeness,
        sections=[
            {
                "title": "MPM gate",
                "rows": [
                    {"label": "Close triggered", "value": mpm.close_triggered, "format": "bool"},
                    {
                        "label": "Intraday triggered",
                        "value": mpm.intraday_triggered,
                        "format": "bool",
                    },
                    {
                        "label": "Effective threshold",
                        "value": mpm.effective_threshold,
                        "format": "percent",
                    },
                    {
                        "label": "Index-adjusted",
                        "value": abs(mpm.index_return) >= MPM_INDEX_ADJUST_MIN_PCT / 100.0,
                        "format": "bool",
                    },
                ],
            },
            {
                "title": "Attribution",
                "rows": [
                    {"label": "Category", "value": attribution.category, "format": "text"},
                    {
                        "label": "Market ratio",
                        "value": attribution.market_ratio,
                        "format": "number",
                    },
                    {"label": "Beta", "value": attribution.beta, "format": "number"},
                    {"label": "Reason", "value": attribution.reason, "format": "text"},
                ],
            },
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
                    {
                        "label": "Classification multiplier",
                        "value": base.classification_multiplier,
                        "format": "number",
                    },
                ],
            },
            {
                "title": "Final score",
                "rows": [
                    {
                        "label": "Decay multiplier",
                        "value": decay.decay_multiplier,
                        "format": "number",
                    },
                    {
                        "label": "Personal multiplier",
                        "value": personal.effective_multiplier,
                        "format": "number",
                    },
                    {"label": "Score", "value": final_score, "format": "number"},
                ],
            },
        ],
    )
