"""Add explicit Rule R2 quality flags to 09:30 snapshots."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "002_index_snapshot_quality"
down_revision = "001_full_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("index_snapshots_0930")}
    if "quality_flag" not in columns:
        op.add_column(
            "index_snapshots_0930",
            sa.Column(
                "quality_flag",
                sa.Text,
                nullable=False,
                server_default="ESTIMATED_FROM_OPEN",
            ),
        )
        op.alter_column("index_snapshots_0930", "quality_flag", server_default=None)
    constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("index_snapshots_0930")
    }
    if "ck_index_snapshots_0930_quality_flag" not in constraints:
        op.create_check_constraint(
            "ck_index_snapshots_0930_quality_flag",
            "index_snapshots_0930",
            "quality_flag IN ('LIVE_0930','BROKER_1M','ESTIMATED_FROM_OPEN')",
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("index_snapshots_0930")
    }
    if "ck_index_snapshots_0930_quality_flag" in constraints:
        op.drop_constraint(
            "ck_index_snapshots_0930_quality_flag",
            "index_snapshots_0930",
            type_="check",
        )
    columns = {column["name"] for column in inspector.get_columns("index_snapshots_0930")}
    if "quality_flag" in columns:
        op.drop_column("index_snapshots_0930", "quality_flag")
