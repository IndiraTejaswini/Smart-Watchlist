"""Add optimistic-concurrency versions to watchlists."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "015_watchlist_versions"
down_revision = "014_watchlist_crud"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "watchlists" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("watchlists")}
    if "version" not in columns:
        op.add_column(
            "watchlists",
            sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        )
    if "updated_at" not in columns:
        op.add_column(
            "watchlists",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "watchlists" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("watchlists")}
    for column in ("updated_at", "version"):
        if column in columns:
            op.drop_column("watchlists", column)
