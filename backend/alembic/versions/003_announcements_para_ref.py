"""Add the announcement paragraph reference used by filing explanations."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "003_announcements_para_ref"
down_revision = "002_index_snapshot_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("announcements")}
    if "para_ref" not in columns:
        op.add_column("announcements", sa.Column("para_ref", sa.String(64)))
    indexes = {index["name"] for index in inspector.get_indexes("announcements")}
    if "ix_announcements_content_hash" not in indexes:
        op.create_index(
            "ix_announcements_content_hash", "announcements", ["content_hash"]
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("announcements")}
    if "ix_announcements_content_hash" in indexes:
        op.drop_index("ix_announcements_content_hash", table_name="announcements")
    columns = {column["name"] for column in inspector.get_columns("announcements")}
    if "para_ref" in columns:
        op.drop_column("announcements", "para_ref")
