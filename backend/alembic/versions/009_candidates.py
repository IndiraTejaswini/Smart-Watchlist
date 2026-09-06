"""Create candidate signal storage."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "009_candidates"
down_revision = "008_market_extremes_adv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidates" in set(inspector.get_table_names()):
        columns = {column["name"] for column in inspector.get_columns("candidates")}
        if "inputs_hash" not in columns:
            op.add_column(
                "candidates",
                sa.Column("inputs_hash", sa.String(64), nullable=True),
            )
            op.execute("UPDATE candidates SET inputs_hash = '' WHERE inputs_hash IS NULL")
            op.alter_column("candidates", "inputs_hash", nullable=False)
        return
    op.create_table(
        "candidates",
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("signal_families", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("primary_signal", sa.String(64), nullable=False),
        sa.Column("sar", sa.Numeric(8, 4), nullable=False),
        sa.Column("turnover_z", sa.Numeric(8, 4)),
        sa.Column("delivery_z", sa.Numeric(8, 4)),
        sa.Column("scar_3d", sa.Numeric(8, 4)),
        sa.Column("has_material_filing", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("inputs_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("date", "symbol"),
    )
    op.create_index(
        "ix_candidates_date_primary_signal",
        "candidates",
        ["date", "primary_signal"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidates" in set(inspector.get_table_names()):
        op.drop_index("ix_candidates_date_primary_signal", table_name="candidates")
        op.drop_table("candidates")
