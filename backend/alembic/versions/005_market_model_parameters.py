"""Create vectorised market-model parameter storage."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "005_market_model_parameters"
down_revision = "004_adjustment_factors_and_view"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "market_model_parameters" in set(inspector.get_table_names()):
        return
    op.create_table(
        "market_model_parameters",
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("alpha", sa.Numeric(10, 6), nullable=False),
        sa.Column("beta", sa.Numeric(8, 4), nullable=False),
        sa.Column("r2", sa.Numeric(6, 4)),
        sa.Column("resid_sd", sa.Numeric(10, 6), nullable=False),
        sa.Column("n_obs", sa.Integer, nullable=False),
        sa.Column(
            "quality_flag",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'CLEAN'"),
        ),
        sa.PrimaryKeyConstraint("symbol", "date"),
    )
    op.create_index(
        "ix_market_model_parameters_date_symbol",
        "market_model_parameters",
        ["date", "symbol"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "market_model_parameters" in set(inspector.get_table_names()):
        op.drop_index(
            "ix_market_model_parameters_date_symbol",
            table_name="market_model_parameters",
        )
        op.drop_table("market_model_parameters")
