"""Create corporate_action_notices — referenced since Task 6.1 but never migrated.

``app.analytics.digest.build_digest`` and ``api/core.py`` already read/write
this table and defensively check ``"corporate_action_notices" in tables``
before doing so, silently skipping ex-date suppression display when it is
absent. It was absent: no earlier migration created it, so the CORPORATE_
ACTION notice — Task 6.1, "the demo's money shot" — has never actually been
persisted or served.
"""

import sqlalchemy as sa
from alembic import op

revision = "020_corporate_action_notices"
down_revision = "019_candidate_sector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "corporate_action_notices" in inspector.get_table_names():
        return
    op.create_table(
        "corporate_action_notices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("ex_date", sa.Date, nullable=False),
        sa.Column("cum_date", sa.Date, nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("as_traded_cum_close", sa.Numeric(14, 4), nullable=False),
        sa.Column("adjusted_prev_close", sa.Numeric(14, 4), nullable=False),
        sa.Column("adjustment_factor", sa.Numeric(14, 8), nullable=False),
        sa.Column("ratio_or_amount", sa.String(64), nullable=False, server_default=""),
        sa.Column("headline", sa.Text, nullable=False),
        sa.Column("detail_text", sa.Text, nullable=False),
        sa.Column("source_url", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_corporate_action_notices_symbol_ex_date",
        "corporate_action_notices",
        ["symbol", "ex_date"],
        unique=True,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "corporate_action_notices" not in inspector.get_table_names():
        return
    op.drop_index(
        "ix_corporate_action_notices_symbol_ex_date", table_name="corporate_action_notices"
    )
    op.drop_table("corporate_action_notices")
