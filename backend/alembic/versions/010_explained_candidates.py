"""Add announcement explainability fields to candidates."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "010_explained_candidates"
down_revision = "009_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidates" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("candidates")}
    if "linked_announcement_ids" not in columns:
        op.add_column(
            "candidates",
            sa.Column(
                "linked_announcement_ids",
                postgresql.ARRAY(sa.String(64)),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )
    if "primary_category" not in columns:
        op.add_column("candidates", sa.Column("primary_category", sa.String(64)))
    if "is_explained" not in columns:
        op.add_column(
            "candidates",
            sa.Column("is_explained", sa.Boolean, nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidates" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("candidates")}
    for column in ("is_explained", "primary_category", "linked_announcement_ids"):
        if column in columns:
            op.drop_column("candidates", column)
