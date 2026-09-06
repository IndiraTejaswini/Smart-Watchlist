"""Create UUID watchlist tables with decimal fractional positions."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "014_watchlist_crud"
down_revision = "013_brief_cursor_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("watchlist_items", "watchlists"):
        op.drop_table(table)
    op.create_table(
        "watchlists",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False, server_default=sa.text("'Default'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("user_id", "name"),
    )
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("watchlist_id", sa.String(36), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("position", sa.Numeric(32, 16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("watchlist_id", "symbol"),
    )
    op.create_index("ix_watchlist_items_order", "watchlist_items", ["watchlist_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_items_order", table_name="watchlist_items")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
    op.create_table(
        "watchlists",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.BigInteger, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("watchlist_id", sa.BigInteger, nullable=False),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("position_key", sa.Text, nullable=False),
        sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
        sa.Column("holding", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
        sa.Column("level_price", sa.Numeric(18, 4)),
        sa.Column("level_set_at", sa.DateTime(timezone=True)),
        sa.Column("last_opened_at", sa.DateTime(timezone=True)),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_items_symbol"),
    )
    op.create_index(
        "ix_watchlist_items_order", "watchlist_items", ["watchlist_id", "position_key"]
    )
