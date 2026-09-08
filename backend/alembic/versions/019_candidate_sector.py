"""Add sector to candidates so sector-wide grouping works against real rows.

``build_digest`` groups candidates by sector at read time; without a persisted
sector on the row, the sector map is always empty against real data and
SECTOR_WIDE can only ever be exercised in unit tests that construct a
``Candidate`` with explicit metadata. This closes that gap.
"""

import sqlalchemy as sa
from alembic import op

revision = "019_candidate_sector"
down_revision = "018_candidate_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidates" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("candidates")}
    if "sector" not in columns:
        op.add_column("candidates", sa.Column("sector", sa.String(64), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidates" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("candidates")}
    if "sector" in columns:
        op.drop_column("candidates", "sector")
