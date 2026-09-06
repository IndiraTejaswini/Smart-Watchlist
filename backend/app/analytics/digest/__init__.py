"""Deterministic digest assembly and hard-cap enforcement.

The package also contains deterministic copy rendering helpers.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from app.analytics.attribution import MarketWideRollup, SectorWideRollup, evaluate_sector_grouping
from app.analytics.candidates import Candidate, SignalFamily
from app.analytics.constants import MAX_ITEMS_PER_SECTOR, SECTOR_DIVERSITY_SAR_OVERRIDE
from app.analytics.corporate_action_notice import CorporateActionNotice
from app.analytics.ranker import PersonalContext, RankedDigestItem, rank_candidate
from app.constants import BRIEF_MAX_ITEMS
from app.crud.brief_cursor import EPOCH, get_brief_cursor, record_brief_served
from app.timeutil import TradingCalendar


@dataclass(frozen=True)
class BriefPayload:
    brief_id: str
    user_id: str
    as_of_ts: datetime
    cursor_ack_ts: datetime
    scored_items: tuple[RankedDigestItem, ...]
    market_rollups: tuple[MarketWideRollup, ...]
    sector_rollups: tuple[SectorWideRollup, ...]
    corporate_actions: tuple[CorporateActionNotice, ...]
    total_candidates_evaluated: int
    inputs_hash: str
    budget: DeliveryBudgetBlock | None = None


@dataclass(frozen=True)
class DeliveryBudgetBlock:
    brief_id: str
    user_id: str
    as_of_ts: datetime
    cursor_ack_ts: datetime
    n_scored_items: int
    n_corporate_actions: int
    n_market_rollups: int
    n_sector_rollups: int
    n_total_delivered: int
    n_candidates_evaluated: int
    n_candidates_delivered: int
    n_suppressed_illiquidity: int
    n_suppressed_refractory: int
    n_suppressed_corporate_action: int
    n_suppressed_rollup: int
    n_suppressed_diversity: int
    n_truncated_hard_cap: int
    inputs_hash: str

    def verify_invariants(self) -> None:
        counts = (
            self.n_scored_items,
            self.n_corporate_actions,
            self.n_market_rollups,
            self.n_sector_rollups,
            self.n_total_delivered,
            self.n_candidates_evaluated,
            self.n_candidates_delivered,
            self.n_suppressed_illiquidity,
            self.n_suppressed_refractory,
            self.n_suppressed_corporate_action,
            self.n_suppressed_rollup,
            self.n_suppressed_diversity,
            self.n_truncated_hard_cap,
        )
        if any(count < 0 for count in counts):
            raise ValueError("delivery budget counts must be non-negative")
        if self.n_total_delivered != (
            self.n_scored_items
            + self.n_corporate_actions
            + self.n_market_rollups
            + self.n_sector_rollups
        ):
            raise ValueError("delivered composition counts do not reconcile")
        if self.n_candidates_evaluated != (
            self.n_candidates_delivered
            + self.n_suppressed_illiquidity
            + self.n_suppressed_refractory
            + self.n_suppressed_corporate_action
            + self.n_suppressed_rollup
            + self.n_suppressed_diversity
            + self.n_truncated_hard_cap
        ):
            raise ValueError("candidate funnel counts do not reconcile")


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
        metadata=dict(row.get("metadata") or {}),
        inputs_hash=str(row.get("inputs_hash", "")),
    )


def _hash_inputs(user_id: str, as_of_ts: datetime, candidates: list[Candidate]) -> str:
    payload = {
        "user_id": user_id,
        "as_of_ts": as_of_ts.isoformat(),
        "candidates": [
            {
                "symbol": item.symbol,
                "date": item.date.isoformat(),
                "sar": item.sar,
                "turnover_z": item.turnover_z,
                "delivery_z": item.delivery_z,
                "inputs_hash": item.inputs_hash,
            }
            for item in candidates
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _context_for_symbol(db: Any, user_id: str, symbol: str) -> PersonalContext:
    del db, user_id, symbol
    return PersonalContext()


def _apply_sector_concentration(
    items: list[RankedDigestItem], sector_map: dict[str, str | None]
) -> list[RankedDigestItem]:
    counts: dict[str, int] = {}
    qualified: list[RankedDigestItem] = []
    for item in items:
        sector = sector_map.get(item.symbol)
        if sector is not None and sector != "UNASSIGNED":
            count = counts.get(sector, 0)
            if (
                count >= MAX_ITEMS_PER_SECTOR
                and abs(item.candidate.sar) < SECTOR_DIVERSITY_SAR_OVERRIDE
            ):
                continue
            counts[sector] = count + 1
        qualified.append(item)
    return qualified


def build_digest(
    db: Any,
    user_id: str,
    as_of_ts: datetime,
    calendar: TradingCalendar,
) -> BriefPayload:
    cursor = get_brief_cursor(db, user_id)
    acknowledged = cursor.acknowledged_through_ts if cursor is not None else EPOCH
    rows = list(
        db.execute(
            sa.text(
                "SELECT * FROM candidates WHERE created_at > :acknowledged "
                "AND created_at <= :as_of_ts ORDER BY date ASC, symbol ASC"
            ),
            {"acknowledged": acknowledged, "as_of_ts": as_of_ts},
        ).mappings()
    )
    all_candidates = [_candidate(row) for row in rows]
    candidates = list(all_candidates)

    notices: tuple[CorporateActionNotice, ...] = ()
    try:
        tables = set(sa.inspect(db).get_table_names())
    except (AttributeError, sa.exc.NoInspectionAvailable):
        tables = set()
    if "corporate_action_notices" in tables:
        notice_rows = db.execute(
            sa.text(
                "SELECT * FROM corporate_action_notices "
                "WHERE ex_date >= :as_of_date"
            ),
            {"as_of_date": as_of_ts.date()},
        ).mappings()
        notices = tuple(CorporateActionNotice(**dict(row)) for row in notice_rows)
    muted = {notice.symbol for notice in notices if notice.ex_date == as_of_ts.date()}
    candidates = [candidate for candidate in candidates if candidate.symbol not in muted]

    sector_map = {
        candidate.symbol: candidate.metadata.get("sector")
        for candidate in candidates
        if candidate.metadata.get("sector") is not None
    }
    retained, sector_rollups = evaluate_sector_grouping(candidates, sector_map)
    scored = [
        rank_candidate(
            candidate,
            as_of_ts.date(),
            _context_for_symbol(db, user_id, candidate.symbol),
            calendar,
        )
        for candidate in retained
    ]
    scored.sort(
        key=lambda item: (
            -item.final_score,
            -abs(item.candidate.sar),
            -float(item.candidate.turnover_z or 0.0),
            item.symbol,
        )
    )
    pre_concentration_count = len(scored)
    scored = _apply_sector_concentration(scored, sector_map)
    diversity_suppressed = pre_concentration_count - len(scored)
    scored_items = tuple(scored[:BRIEF_MAX_ITEMS])
    truncated = len(scored) - len(scored_items)
    rollup_suppressed = sum(len(rollup.affected_symbols) for rollup in sector_rollups)
    corporate_suppressed = len(all_candidates) - len(candidates)
    brief_id = hashlib.sha256(f"{user_id}:{as_of_ts.isoformat()}".encode()).hexdigest()
    input_hash = _hash_inputs(user_id, as_of_ts, all_candidates)
    served = record_brief_served(db, user_id, "brief:default", as_of_ts)
    budget = DeliveryBudgetBlock(
        brief_id=brief_id,
        user_id=user_id,
        as_of_ts=as_of_ts,
        cursor_ack_ts=served.acknowledged_through_ts,
        n_scored_items=len(scored_items),
        n_corporate_actions=len(notices),
        n_market_rollups=0,
        n_sector_rollups=len(sector_rollups),
        n_total_delivered=len(scored_items) + len(notices) + len(sector_rollups),
        n_candidates_evaluated=len(all_candidates),
        n_candidates_delivered=len(scored_items),
        n_suppressed_illiquidity=0,
        n_suppressed_refractory=0,
        n_suppressed_corporate_action=corporate_suppressed,
        n_suppressed_rollup=rollup_suppressed,
        n_suppressed_diversity=diversity_suppressed,
        n_truncated_hard_cap=truncated,
        inputs_hash=input_hash,
    )
    budget.verify_invariants()
    return BriefPayload(
        brief_id=brief_id,
        user_id=user_id,
        as_of_ts=as_of_ts,
        cursor_ack_ts=served.acknowledged_through_ts,
        scored_items=scored_items,
        market_rollups=(),
        sector_rollups=tuple(sector_rollups),
        corporate_actions=notices,
        total_candidates_evaluated=len(all_candidates),
        inputs_hash=input_hash,
        budget=budget,
    )
