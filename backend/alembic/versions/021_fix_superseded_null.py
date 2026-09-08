"""Fix superseded_by_id wrongly forced NOT NULL by 018's blanket alter_column.

NULL is that column's meaning ("this candidate has not been superseded");
018's own partial index (``idx_active_candidates ... WHERE superseded_by_id
IS NULL``) depends on it being nullable. Only affects databases that already
ran 018 before its loop bug was fixed.
"""

import sqlalchemy as sa
from alembic import op

revision = "021_fix_superseded_null"
down_revision = "020_corporate_action_notices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidates" not in inspector.get_table_names():
        return
    columns = {column["name"]: column for column in inspector.get_columns("candidates")}
    if "superseded_by_id" in columns and not columns["superseded_by_id"]["nullable"]:
        op.alter_column("candidates", "superseded_by_id", nullable=True)


def downgrade() -> None:
    pass
