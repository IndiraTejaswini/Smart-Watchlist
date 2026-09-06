"""Create empirical-logit delivery baseline storage."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "007_delivery_baselines"
down_revision = "006_turnover_baselines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "delivery_baselines" in set(inspector.get_table_names()):
        return
    op.create_table(
        "delivery_baselines",
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("raw_delivery_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("logit_delivery", sa.Numeric(10, 6), nullable=False),
        sa.Column("mean_logit_20d", sa.Numeric(10, 6), nullable=False),
        sa.Column("std_logit_20d", sa.Numeric(10, 6), nullable=False),
        sa.Column("delivery_z_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("n_obs", sa.Integer, nullable=False),
        sa.Column(
            "quality_flag",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'CLEAN'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("symbol", "date"),
    )
    op.create_index(
        "ix_delivery_baselines_date_symbol",
        "delivery_baselines",
        ["date", "symbol"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "delivery_baselines" in set(inspector.get_table_names()):
        op.drop_index("ix_delivery_baselines_date_symbol", table_name="delivery_baselines")
        op.drop_table("delivery_baselines")
