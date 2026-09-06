"""Dual-threshold liquidity hysteresis and state persistence helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date as date_type
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from app.analytics.candidates import Candidate

THRESHOLD_LOW = Decimal("8000000.00")
THRESHOLD_HIGH = Decimal("12000000.00")
THRESHOLD_INIT = Decimal("10000000.00")


@dataclass(frozen=True)
class LiquidityStateResult:
    symbol: str
    date: date_type
    is_liquid: bool
    adv_20d: Decimal
    state_flipped: bool
    last_state_change_date: date_type


def evaluate_liquidity_state(
    symbol: str,
    current_date: date_type,
    adv_20d: Decimal,
    prior_state: LiquidityStateResult | None,
) -> LiquidityStateResult:
    """Evaluate one day's state using separate exit and re-entry thresholds."""
    if prior_state is None:
        return LiquidityStateResult(
            symbol, current_date, adv_20d >= THRESHOLD_INIT, adv_20d, True, current_date
        )
    if prior_state.is_liquid:
        is_liquid = adv_20d >= THRESHOLD_LOW
    else:
        is_liquid = adv_20d > THRESHOLD_HIGH
    flipped = is_liquid != prior_state.is_liquid
    return LiquidityStateResult(
        symbol=symbol,
        date=current_date,
        is_liquid=is_liquid,
        adv_20d=adv_20d,
        state_flipped=flipped,
        last_state_change_date=current_date if flipped else prior_state.last_state_change_date,
    )


def tag_liquidity(candidate: Candidate, state: LiquidityStateResult) -> Candidate:
    """Annotate a candidate for downstream filtering and audit output."""
    metadata = dict(candidate.metadata)
    metadata["is_liquid"] = state.is_liquid
    metadata["adv_20d"] = state.adv_20d
    return replace(candidate, metadata=metadata)


def filter_illiquid_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Drop candidates explicitly marked illiquid; unknown state is retained."""
    return [
        candidate
        for candidate in candidates
        if candidate.metadata.get("is_liquid") is not False
    ]


def load_liquidity_state(conn: Any, symbol: str) -> LiquidityStateResult | None:
    row = conn.execute(
        sa.text(
            "SELECT symbol, date, is_liquid, adv_20d, last_state_change_date "
            "FROM symbol_liquidity_state WHERE symbol = :symbol"
        ),
        {"symbol": symbol},
    ).mappings().first()
    if row is None:
        return None
    return LiquidityStateResult(
        symbol=str(row["symbol"]),
        date=row["date"],
        is_liquid=bool(row["is_liquid"]),
        adv_20d=Decimal(str(row["adv_20d"])),
        state_flipped=False,
        last_state_change_date=row["last_state_change_date"],
    )


def persist_liquidity_state(conn: Any, state: LiquidityStateResult) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO symbol_liquidity_state "
            "(symbol, date, is_liquid, adv_20d, last_state_change_date) "
            "VALUES (:symbol, :date, :is_liquid, :adv_20d, :last_state_change_date) "
            "ON CONFLICT (symbol) DO UPDATE SET date = EXCLUDED.date, "
            "is_liquid = EXCLUDED.is_liquid, adv_20d = EXCLUDED.adv_20d, "
            "last_state_change_date = EXCLUDED.last_state_change_date, "
            "updated_at = NOW()"
        ),
        {
            "symbol": state.symbol,
            "date": state.date,
            "is_liquid": state.is_liquid,
            "adv_20d": state.adv_20d,
            "last_state_change_date": state.last_state_change_date,
        },
    )

