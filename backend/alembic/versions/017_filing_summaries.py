"""Create bounded filing summary audit storage."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "017_filing_summaries"
down_revision = "016_digest_delivery_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "filing_summaries" in set(inspector.get_table_names()):
        return
    op.create_table(
        "filing_summaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("brief_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("announcement_id", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("prompt_text", sa.Text, nullable=False),
        sa.Column("raw_output", sa.Text),
        sa.Column("is_valid", sa.Boolean, nullable=False),
        sa.Column("validation_failure_reason", sa.String(128)),
        sa.Column("sanitized_sentence", sa.String(256)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_filing_summaries_announcement", "filing_summaries", ["announcement_id"])
    op.create_index("ix_filing_summaries_brief_symbol", "filing_summaries", ["brief_id", "symbol"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "filing_summaries" not in set(inspector.get_table_names()):
        return
    indexes = {index["name"] for index in inspector.get_indexes("filing_summaries")}
    for name in ("ix_filing_summaries_brief_symbol", "ix_filing_summaries_announcement"):
        if name in indexes:
            op.drop_index(name, table_name="filing_summaries")
    op.drop_table("filing_summaries")
