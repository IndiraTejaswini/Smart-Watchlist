"""Create lagged turnover baseline storage."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "006_turnover_baselines"
down_revision = "005_market_model_parameters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "turnover_baselines" in set(inspector.get_table_names()):
        return
    op.create_table(
        "turnover_baselines",
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("mean_log_turnover", sa.Numeric(12, 6), nullable=False),
        sa.Column("std_log_turnover", sa.Numeric(12, 6), nullable=False),
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
        "ix_turnover_baselines_date_symbol",
        "turnover_baselines",
        ["date", "symbol"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "turnover_baselines" in set(inspector.get_table_names()):
        op.drop_index("ix_turnover_baselines_date_symbol", table_name="turnover_baselines")
        op.drop_table("turnover_baselines")
