"""Add provisional/final candidate revisions."""

import sqlalchemy as sa
from alembic import op

revision = "018_candidate_revisions"
down_revision = "017_filing_summaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidates" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("candidates")}
    if "id" not in columns:
        op.add_column("candidates", sa.Column("id", sa.String(36), nullable=True))
        op.execute("UPDATE candidates SET id = date || ':' || symbol WHERE id IS NULL")
    additions = (
        ("revision", sa.Integer(), "1"),
        ("status", sa.String(16), "'PROVISIONAL'"),
        ("was_restated", sa.Boolean(), "FALSE"),
        ("superseded_by_id", sa.String(36), None),
    )
    for name, column, default in additions:
        if name not in columns:
            op.add_column("candidates", sa.Column(name, column, nullable=True))
            if default is not None:
                op.execute(sa.text(f"UPDATE candidates SET {name} = {default}"))
            op.alter_column("candidates", name, nullable=False)
    op.alter_column("candidates", "delivery_z", nullable=True)
    if "delivery_fraction" in columns:
        op.alter_column("candidates", "delivery_fraction", nullable=True)
    op.create_index(
        "ix_candidates_symbol_date_revision", "candidates", ["symbol", "date", "revision"]
    )
    op.create_index("ix_candidates_superseded_by", "candidates", ["superseded_by_id"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_active_candidates "
        "ON candidates (date, status) WHERE superseded_by_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_active_candidates")
    op.drop_index("ix_candidates_superseded_by", table_name="candidates")
    op.drop_index("ix_candidates_symbol_date_revision", table_name="candidates")
    for name in ("superseded_by_id", "was_restated", "status", "revision", "id"):
        op.drop_column("candidates", name)
