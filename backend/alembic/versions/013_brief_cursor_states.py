"""Create dual delivered and acknowledged brief cursors."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "013_brief_cursor_states"
down_revision = "012_read_cursors_monotonic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "brief_cursor_states" in set(inspector.get_table_names()):
        return
    epoch = sa.text("'1970-01-01 00:00:00+00'")
    op.create_table(
        "brief_cursor_states",
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column(
            "feed_id",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'brief:default'"),
        ),
        sa.Column(
            "seen_through_ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=epoch,
        ),
        sa.Column(
            "acknowledged_through_ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=epoch,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("user_id", "feed_id"),
    )
    op.create_index(
        "ix_brief_cursor_states_user_feed",
        "brief_cursor_states",
        ["user_id", "feed_id"],
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_brief_cursor_states_user_feed")
    op.drop_table("brief_cursor_states")
