"""Create adjusted-price extremes and ADV storage."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "008_market_extremes_adv"
down_revision = "007_delivery_baselines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "market_extremes_adv" in set(inspector.get_table_names()):
        return
    op.create_table(
        "market_extremes_adv",
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("high_52w", sa.Numeric(12, 4), nullable=False),
        sa.Column("low_52w", sa.Numeric(12, 4), nullable=False),
        sa.Column("distance_to_52w_high_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("distance_to_52w_low_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("adv_20d", sa.Numeric(16, 2), nullable=False),
        sa.Column("n_obs_52w", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("symbol", "date"),
    )
    op.create_index(
        "ix_market_extremes_adv_date_symbol",
        "market_extremes_adv",
        ["date", "symbol"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "market_extremes_adv" in set(inspector.get_table_names()):
        op.drop_index(
            "ix_market_extremes_adv_date_symbol",
            table_name="market_extremes_adv",
        )
        op.drop_table("market_extremes_adv")
