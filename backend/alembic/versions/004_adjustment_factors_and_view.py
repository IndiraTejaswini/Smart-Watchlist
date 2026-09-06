"""Create read-time corporate-action adjustment factors and adjusted bars view."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "004_adjustment_factors_and_view"
down_revision = "003_announcements_para_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "symbol_adjustment_factors" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("symbol_adjustment_factors")
        }
        if "trade_date" in columns and "date" not in columns:
            op.alter_column(
                "symbol_adjustment_factors",
                "trade_date",
                new_column_name="date",
            )
        if "cum_vol_factor" not in columns:
            op.add_column(
                "symbol_adjustment_factors",
                sa.Column(
                    "cum_vol_factor",
                    sa.Numeric(14, 8),
                    nullable=False,
                    server_default=sa.text("1.0"),
                ),
            )
        if "updated_at" not in columns:
            op.add_column(
                "symbol_adjustment_factors",
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("NOW()"),
                ),
            )
    else:
        op.create_table(
            "symbol_adjustment_factors",
            sa.Column("symbol", sa.String(32), nullable=False),
            sa.Column(
                "date",
                sa.Date,
                nullable=False,
            ),
            sa.Column(
                "cum_price_factor",
                sa.Numeric(14, 8),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
            sa.Column(
                "cum_tr_factor",
                sa.Numeric(14, 8),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
            sa.Column(
                "cum_vol_factor",
                sa.Numeric(14, 8),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("NOW()"),
            ),
            sa.PrimaryKeyConstraint("symbol", "date"),
        )

    op.execute("DROP VIEW IF EXISTS v_adjusted_bars")
    op.execute(
        """
        CREATE VIEW v_adjusted_bars AS
        SELECT
            b.symbol,
            b.date,
            ROUND(b.open * COALESCE(f.cum_price_factor, 1.0), 4) AS adj_open,
            ROUND(b.high * COALESCE(f.cum_price_factor, 1.0), 4) AS adj_high,
            ROUND(b.low * COALESCE(f.cum_price_factor, 1.0), 4) AS adj_low,
            ROUND(b.close * COALESCE(f.cum_price_factor, 1.0), 4) AS adj_close,
            ROUND(b.volume * COALESCE(f.cum_vol_factor, 1.0), 0) AS adj_volume,
            b.open AS raw_open,
            b.close AS raw_close,
            b.volume AS raw_volume
        FROM daily_bars b
        LEFT JOIN symbol_adjustment_factors f
          ON b.symbol = f.symbol AND b.date = f.date
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_adjusted_bars")
    inspector = sa.inspect(op.get_bind())
    if "symbol_adjustment_factors" in set(inspector.get_table_names()):
        columns = {
            column["name"] for column in inspector.get_columns("symbol_adjustment_factors")
        }
        for column in ("updated_at", "cum_vol_factor"):
            if column in columns:
                op.drop_column("symbol_adjustment_factors", column)
        if "date" in columns:
            op.alter_column(
                "symbol_adjustment_factors",
                "date",
                new_column_name="trade_date",
            )
