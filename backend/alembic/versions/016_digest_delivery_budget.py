"""Add detailed digest delivery budget accounting."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "016_digest_delivery_budget"
down_revision = "015_watchlist_versions"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("brief_id", sa.String(64), ""),
    ("user_id", sa.String(64), ""),
    ("as_of_ts", sa.DateTime(timezone=True), None),
    ("cursor_ack_ts", sa.DateTime(timezone=True), None),
    ("n_scored_items", sa.Integer, 0),
    ("n_corporate_actions", sa.Integer, 0),
    ("n_market_rollups", sa.Integer, 0),
    ("n_sector_rollups", sa.Integer, 0),
    ("n_total_delivered", sa.Integer, 0),
    ("n_candidates_evaluated", sa.Integer, 0),
    ("n_candidates_delivered", sa.Integer, 0),
    ("n_suppressed_illiquidity", sa.Integer, 0),
    ("n_suppressed_refractory", sa.Integer, 0),
    ("n_suppressed_corporate_action", sa.Integer, 0),
    ("n_suppressed_rollup", sa.Integer, 0),
    ("n_suppressed_diversity", sa.Integer, 0),
    ("n_truncated_hard_cap", sa.Integer, 0),
    ("inputs_hash", sa.String(64), ""),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "digest_deliveries" not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns("digest_deliveries")}
    for name, column_type, default in _COLUMNS:
        if name not in existing:
            kwargs = {"nullable": True}
            if default is not None:
                kwargs["server_default"] = sa.text(
                    f"'{default}'" if isinstance(default, str) else str(default)
                )
            op.add_column("digest_deliveries", sa.Column(name, column_type, **kwargs))
    op.create_index(
        "ix_digest_deliveries_brief_id", "digest_deliveries", ["brief_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_digest_deliveries_user_as_of", "digest_deliveries", ["user_id", "as_of_ts"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_digest_deliveries_inputs_hash", "digest_deliveries", ["inputs_hash"],
        if_not_exists=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "digest_deliveries" not in set(inspector.get_table_names()):
        return
    indexes = {index["name"] for index in inspector.get_indexes("digest_deliveries")}
    for index_name in (
        "ix_digest_deliveries_inputs_hash",
        "ix_digest_deliveries_brief_id",
        "ix_digest_deliveries_user_as_of",
    ):
        if index_name in indexes:
            op.drop_index(index_name, table_name="digest_deliveries")
    existing = {column["name"] for column in inspector.get_columns("digest_deliveries")}
    for name, _, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("digest_deliveries", name)
