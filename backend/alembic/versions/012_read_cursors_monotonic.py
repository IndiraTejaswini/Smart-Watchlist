"""Create monotonic feed read cursors."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "012_read_cursors_monotonic"
down_revision = "011_symbol_liquidity_state"
branch_labels = None
depends_on = None


def _create_target_table() -> None:
    op.create_table(
        "read_cursors",
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("feed_id", sa.String(64), nullable=False),
        sa.Column("last_read_seq", sa.BigInteger, nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("user_id", "feed_id"),
    )
    op.create_index(
        "ix_read_cursors_user_feed",
        "read_cursors",
        ["user_id", "feed_id"],
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "read_cursors" in set(inspector.get_table_names()):
        op.drop_table("read_cursors")
    _create_target_table()


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "read_cursors" in set(inspector.get_table_names()):
        op.execute("DROP INDEX IF EXISTS ix_read_cursors_user_feed")
        op.drop_table("read_cursors")
    op.create_table(
        "read_cursors",
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("scope_type", sa.Text, nullable=False),
        sa.Column("scope_id", sa.Text, nullable=False),
        sa.Column("seen_through_ts", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_through_ts", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_device_id", sa.Text),
        sa.PrimaryKeyConstraint("user_id", "scope_type", "scope_id"),
        sa.CheckConstraint(
            "scope_type IN ('SYMBOL','WATCHLIST','GLOBAL')",
            name="ck_read_cursors_scope_type",
        ),
    )
