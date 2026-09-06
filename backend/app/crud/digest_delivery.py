"""Persistence for digest delivery accounting."""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.analytics.digest import DeliveryBudgetBlock


def persist_digest_delivery(db: Session, budget: DeliveryBudgetBlock) -> None:
    budget.verify_invariants()
    db.execute(
        sa.text(
            "INSERT INTO digest_deliveries "
            "(id, brief_id, user_id, as_of_ts, cursor_ack_ts, "
            "n_scored_items, n_corporate_actions, n_market_rollups, n_sector_rollups, "
            "n_total_delivered, n_candidates_evaluated, n_candidates_delivered, "
            "n_suppressed_illiquidity, n_suppressed_refractory, "
            "n_suppressed_corporate_action, n_suppressed_rollup, "
            "n_suppressed_diversity, n_truncated_hard_cap, inputs_hash) "
            "VALUES (:id, :brief_id, :user_id, :as_of_ts, :cursor_ack_ts, "
            ":n_scored_items, :n_corporate_actions, :n_market_rollups, :n_sector_rollups, "
            ":n_total_delivered, :n_candidates_evaluated, :n_candidates_delivered, "
            ":n_suppressed_illiquidity, :n_suppressed_refractory, "
            ":n_suppressed_corporate_action, :n_suppressed_rollup, "
            ":n_suppressed_diversity, :n_truncated_hard_cap, :inputs_hash)"
        ),
        {
            "id": str(uuid4()),
            **{field: getattr(budget, field) for field in (
                "brief_id", "user_id", "as_of_ts", "cursor_ack_ts",
                "n_scored_items", "n_corporate_actions", "n_market_rollups",
                "n_sector_rollups", "n_total_delivered", "n_candidates_evaluated",
                "n_candidates_delivered", "n_suppressed_illiquidity",
                "n_suppressed_refractory", "n_suppressed_corporate_action",
                "n_suppressed_rollup", "n_suppressed_diversity",
                "n_truncated_hard_cap", "inputs_hash",
            )}
        },
    )
    db.commit()
