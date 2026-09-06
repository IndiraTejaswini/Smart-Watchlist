"""Persist per-symbol liquidity hysteresis state."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "011_symbol_liquidity_state"
down_revision = "010_explained_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "symbol_liquidity_state" not in tables:
        op.create_table(
            "symbol_liquidity_state",
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column("date", sa.Date, nullable=False),
            sa.Column("is_liquid", sa.Boolean, nullable=False),
            sa.Column("adv_20d", sa.Numeric(16, 2), nullable=False),
            sa.Column("last_state_change_date", sa.Date, nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.PrimaryKeyConstraint("symbol"),
        )
    else:
        columns = {column["name"] for column in inspector.get_columns("symbol_liquidity_state")}
        if "state" in columns:
            op.add_column(
                "symbol_liquidity_state",
                sa.Column("date", sa.Date, nullable=True),
            )
            op.add_column(
                "symbol_liquidity_state",
                sa.Column("is_liquid", sa.Boolean, nullable=True),
            )
            op.add_column(
                "symbol_liquidity_state",
                sa.Column("adv_20d", sa.Numeric(16, 2), nullable=True),
            )
            op.add_column(
                "symbol_liquidity_state",
                sa.Column("last_state_change_date", sa.Date, nullable=True),
            )
            op.add_column(
                "symbol_liquidity_state",
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=True,
                    server_default=sa.text("NOW()"),
                ),
            )
            op.execute(
                "UPDATE symbol_liquidity_state SET "
                "date = changed_at::date, "
                "is_liquid = (state = 'ACTIVE'), "
                "adv_20d = 0, "
                "last_state_change_date = changed_at::date"
            )
            op.alter_column("symbol_liquidity_state", "date", nullable=False)
            op.alter_column("symbol_liquidity_state", "is_liquid", nullable=False)
            op.alter_column("symbol_liquidity_state", "adv_20d", nullable=False)
            op.alter_column(
                "symbol_liquidity_state", "last_state_change_date", nullable=False
            )
            op.alter_column("symbol_liquidity_state", "updated_at", nullable=False)
            op.drop_constraint(
                "ck_symbol_liquidity_state_state",
                "symbol_liquidity_state",
                type_="check",
            )
            op.drop_column("symbol_liquidity_state", "state")
            op.drop_column("symbol_liquidity_state", "changed_at")
    indexes = {index["name"] for index in inspector.get_indexes("symbol_liquidity_state")}
    if "ix_symbol_liquidity_state_date_is_liquid" not in indexes:
        op.create_index(
            "ix_symbol_liquidity_state_date_is_liquid",
            "symbol_liquidity_state",
            ["date", "is_liquid"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "symbol_liquidity_state" in set(inspector.get_table_names()):
        op.execute("DROP INDEX IF EXISTS ix_symbol_liquidity_state_date_is_liquid")
        columns = {column["name"] for column in inspector.get_columns("symbol_liquidity_state")}
        if "state" not in columns:
            op.add_column(
                "symbol_liquidity_state",
                sa.Column("state", sa.Text, nullable=True, server_default=sa.text("'ACTIVE'")),
            )
            op.add_column(
                "symbol_liquidity_state",
                sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
            )
            op.execute(
                "UPDATE symbol_liquidity_state SET "
                "state = CASE WHEN is_liquid THEN 'ACTIVE' ELSE 'SUPPRESSED' END, "
                "changed_at = last_state_change_date::timestamp"
            )
            op.alter_column("symbol_liquidity_state", "state", nullable=False)
            op.alter_column("symbol_liquidity_state", "changed_at", nullable=False)
            op.create_check_constraint(
                "ck_symbol_liquidity_state_state",
                "symbol_liquidity_state",
                "state IN ('ACTIVE','SUPPRESSED')",
            )
            for column in (
                "updated_at",
                "last_state_change_date",
                "adv_20d",
                "is_liquid",
                "date",
            ):
                op.drop_column("symbol_liquidity_state", column)
