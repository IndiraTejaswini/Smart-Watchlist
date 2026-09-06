"""001: full schema

Every table in ARCHITECTURE.md §5, §6, §7, §9, §12 and §20.

Written as explicit DDL, in the order the foreign keys require, and dropped in
the reverse order so `downgrade base` is a clean teardown.

Two rules from the specification are load-bearing here and are called out where
they appear:

  - `daily_bars` PK is (symbol, date), NOT (symbol, date, series). §6.2: a
    symbol has exactly one series on a given day, so adding `series` to the key
    would *permit* the duplicate rows it looks like it prevents.
  - Provenance is mandatory (R4, N2). Every ingested fact carries `source` and
    `ingested_at`; every derived row carries `computed_at`. NOT NULL, so it
    cannot be skipped.

Revision ID: 001_full_schema
Revises:
Create Date: 2026-09-06
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.constants import BRIEF_MAX_ITEMS

revision = "001_full_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── §5.1 Symbol master ─────────────────────────────────────────────────
    # instrument_id is the immutable identity; fact tables key on `symbol` for
    # query and log readability, and symbol_aliases stitches renames together.
    op.create_table(
        "instruments",
        sa.Column("instrument_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text, nullable=False, unique=True),
        sa.Column("isin", sa.Text),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("series", sa.Text, nullable=False),
        # 'UNASSIGNED', never NULL — the last tier of the §5.1 fallback chain.
        sa.Column(
            "sector", sa.Text, nullable=False, server_default=sa.text("'UNASSIGNED'")
        ),
        sa.Column("sector_source", sa.Text, nullable=False),
        sa.Column("industry", sa.Text),
        sa.Column("face_value", sa.Numeric(12, 4)),
        sa.Column("listing_date", sa.Date),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.text("TRUE")
        ),
        sa.Column(
            "primary_venue", sa.Text, nullable=False, server_default=sa.text("'NSE'")
        ),
        sa.Column(
            "has_derivatives",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.CheckConstraint(
            "sector_source IN ('PRIMARY_FILE','INDEX_MAP','VENDOR','UNASSIGNED')",
            name="ck_instruments_sector_source",
        ),
    )
    # The §6.2 row-count floor counts active instruments on every ingest.
    op.create_index(
        "ix_instruments_active",
        "instruments",
        ["is_active"],
        postgresql_where=sa.text("is_active"),
    )
    op.create_index("ix_instruments_sector", "instruments", ["sector"])

    op.create_table(
        "symbol_aliases",
        sa.Column("old_symbol", sa.Text, primary_key=True),
        sa.Column(
            "instrument_id",
            sa.BigInteger,
            sa.ForeignKey("instruments.instrument_id", ondelete="CASCADE"),
        ),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("note", sa.Text),
    )

    # Nightly JSONB snapshot instead of SCD Type 2 — same audit trail, without
    # an as_of predicate on every reference-data query. §5.1.
    op.create_table(
        "symbol_master_snapshots",
        sa.Column("snapshot_date", sa.Date, primary_key=True),
        sa.Column("instrument_id", sa.BigInteger, primary_key=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
    )

    # ─── §5.2 Trading calendar ──────────────────────────────────────────────
    # A session state machine, not a boolean: pre-open equilibrium prices would
    # otherwise generate false gap alerts at open, and Muhurat and half-day
    # sessions break naive session-window logic.
    op.create_table(
        "trading_calendar",
        sa.Column("calendar_date", sa.Date, primary_key=True),
        sa.Column("is_trading_day", sa.Boolean, nullable=False),
        sa.Column("pre_open_start", sa.DateTime(timezone=True)),
        sa.Column("pre_open_end", sa.DateTime(timezone=True)),
        sa.Column("regular_open", sa.DateTime(timezone=True)),
        sa.Column("regular_close", sa.DateTime(timezone=True)),
        sa.Column("post_close_end", sa.DateTime(timezone=True)),
        sa.Column(
            "session_type", sa.Text, nullable=False, server_default=sa.text("'REGULAR'")
        ),
        sa.Column("notes", sa.Text),
        sa.CheckConstraint(
            "session_type IN ('REGULAR','MUHURAT','HALF_DAY','CLOSED')",
            name="ck_trading_calendar_session_type",
        ),
    )
    op.create_index(
        "ix_trading_calendar_trading_days",
        "trading_calendar",
        ["calendar_date"],
        postgresql_where=sa.text("is_trading_day"),
    )

    # ─── §5.3 Corporate actions ─────────────────────────────────────────────
    # price_factor covers splits and bonuses only (PRI); cash dividends leave it
    # at 1.0 and populate tr_factor (TRI). R10 — do not dividend-adjust prices.
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("ex_date", sa.Date, nullable=False),
        sa.Column("record_date", sa.Date),
        sa.Column("action_type", sa.Text, nullable=False),
        sa.Column("ratio_text", sa.Text),
        sa.Column("purpose_raw", sa.Text, nullable=False),
        sa.Column("price_factor", sa.Numeric(18, 10)),
        sa.Column("tr_factor", sa.Numeric(18, 10)),
        sa.Column("verification", sa.Text, nullable=False),
        sa.Column("observed_gap", sa.Numeric(12, 6)),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "symbol",
            "ex_date",
            "action_type",
            "purpose_raw",
            name="uq_corporate_actions_natural",
        ),
        sa.CheckConstraint(
            "action_type IN ('BONUS','SPLIT','CONSOLIDATION','DIVIDEND','RIGHTS',"
            "'DEMERGER','COMPOSITE','UNPARSED')",
            name="ck_corporate_actions_action_type",
        ),
        sa.CheckConstraint(
            "verification IN ('VERIFIED','INFERRED','DISCREPANCY','UNVERIFIED',"
            "'UNPARSED')",
            name="ck_corporate_actions_verification",
        ),
    )
    # §4.3: ex-dates are matched on the IST trading date, and the suppression
    # path in §11.1 looks up by (symbol, ex_date) on every candidate.
    op.create_index(
        "ix_corporate_actions_symbol_ex_date", "corporate_actions", ["symbol", "ex_date"]
    )
    op.create_index("ix_corporate_actions_ex_date", "corporate_actions", ["ex_date"])

    # ─── §6 EOD ingest bookkeeping ──────────────────────────────────────────
    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("target_date", sa.Date),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("rows", sa.Integer),
        sa.Column("file_hash", sa.CHAR(64)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text),
        sa.CheckConstraint(
            "status IN ('OK','FAILED','ESCALATED','SKIPPED_CACHED','SKIPPED_HOLIDAY_STALE')",
            name="ck_ingest_runs_status",
        ),
    )
    # §6.2 rule 3: a matching file_hash for the same source and date skips
    # parsing entirely, so this lookup runs on every ingest.
    op.create_index(
        "ix_ingest_runs_source_date", "ingest_runs", ["source", "target_date"]
    )

    # Rejected rows are quarantined, never dropped — §6.2 rule 5.
    op.create_table(
        "ingest_quarantine",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ingest_run_id", sa.BigInteger, sa.ForeignKey("ingest_runs.id")),
        sa.Column("source_file", sa.Text),
        sa.Column("raw_payload", postgresql.JSONB, nullable=False),
        sa.Column("rejection_reason", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_ingest_quarantine_reason", "ingest_quarantine", ["rejection_reason"]
    )

    # ─── §20 daily_bars ─────────────────────────────────────────────────────
    # PK is (symbol, date) — NOT (symbol, date, series). See the module
    # docstring. `series` is a column.
    op.create_table(
        "daily_bars",
        sa.Column("symbol", sa.Text, primary_key=True),
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("prev_close", sa.Numeric(18, 4)),
        sa.Column("vwap", sa.Numeric(18, 4)),
        sa.Column("volume", sa.BigInteger),
        sa.Column("turnover", sa.Numeric(24, 4)),
        sa.Column("trades", sa.BigInteger),
        sa.Column("upper_band", sa.Numeric(18, 4)),
        sa.Column("lower_band", sa.Numeric(18, 4)),
        sa.Column("series", sa.Text),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        # The §6.2 rule-4 validators, enforced by the database as well as the
        # loader. A bar that fails these is quarantined, never committed.
        sa.CheckConstraint("high >= low", name="ck_daily_bars_high_ge_low"),
        sa.CheckConstraint(
            "high >= GREATEST(open, close)", name="ck_daily_bars_high_ge_open_close"
        ),
        sa.CheckConstraint(
            "low <= LEAST(open, close)", name="ck_daily_bars_low_le_open_close"
        ),
        sa.CheckConstraint("volume >= 0", name="ck_daily_bars_volume_nonneg"),
    )
    op.create_index("ix_daily_bars_date", "daily_bars", ["date"])

    # Nifty 50 EOD OHLC — the r_m series behind the §8.1 market model.
    # Kept separate from daily_bars so that the §6.2 row-count check, which
    # compares daily_bars rows against the count of active instruments, is not
    # skewed by index rows.
    op.create_table(
        "index_bars",
        sa.Column("index_symbol", sa.Text, primary_key=True),
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("open", sa.Numeric(18, 4)),
        sa.Column("high", sa.Numeric(18, 4)),
        sa.Column("low", sa.Numeric(18, 4)),
        sa.Column("close", sa.Numeric(18, 4)),
        sa.Column("prev_close", sa.Numeric(18, 4)),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("high >= low", name="ck_index_bars_high_ge_low"),
    )

    # ─── §6.1 The 09:30 index snapshot ──────────────────────────────────────
    # A hard requirement: the MPM framework freezes the benchmark change at
    # 09:30 and uses that frozen value for the whole session. It cannot be
    # reconstructed from EOD data, so `source` records which tier of the
    # backfill priority matrix supplied it and ESTIMATED_FROM_OPEN raises a
    # data-quality flag on every signal derived from that date.
    op.create_table(
        "index_snapshots_0930",
        sa.Column("index_symbol", sa.Text, primary_key=True),
        sa.Column("trading_date", sa.Date, primary_key=True),
        sa.Column("value", sa.Numeric(18, 4), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('CAPTURED_LIVE','BROKER_CANDLE','ESTIMATED_FROM_OPEN')",
            name="ck_index_snapshots_0930_source",
        ),
    )

    # ─── §8.3 Delivery ──────────────────────────────────────────────────────
    # traded_qty and deliverable_qty are stored as reported; the percentage is
    # stored too because "delivery was 76% against a 20-day average of 41%" is
    # what the user reads (§8.3). The logit is derived, never stored here.
    op.create_table(
        "delivery_stats",
        sa.Column("symbol", sa.Text, primary_key=True),
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("traded_qty", sa.BigInteger),
        sa.Column("deliverable_qty", sa.BigInteger),
        sa.Column("delivery_pct", sa.Numeric(8, 5)),
        sa.Column("series", sa.Text),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        # §6.2 rule 4. More deliverable than traded is impossible.
        sa.CheckConstraint(
            "deliverable_qty <= traded_qty", name="ck_delivery_stats_deliv_le_traded"
        ),
        sa.CheckConstraint("traded_qty >= 0", name="ck_delivery_stats_traded_nonneg"),
    )
    op.create_index("ix_delivery_stats_date", "delivery_stats", ["date"])

    # ─── §7.1 Adjustment factors ────────────────────────────────────────────
    # A factor table, not row rewriting: a corporate action inserts factors
    # rather than rewriting a symbol's entire bar history.
    op.create_table(
        "symbol_adjustment_factors",
        sa.Column("symbol", sa.Text, primary_key=True),
        sa.Column("trade_date", sa.Date, primary_key=True),
        sa.Column(
            "cum_price_factor",
            sa.Numeric(18, 10),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.Column(
            "cum_tr_factor",
            sa.Numeric(18, 10),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )

    # ─── §8 Baselines ───────────────────────────────────────────────────────
    # One row per symbol per trading date, holding every rolling statistic the
    # signal engine consumes. `quality` carries the §8.1 DEGRADED path for a
    # symbol with fewer than BETA_MIN_OBS observations.
    op.create_table(
        "baselines",
        sa.Column("symbol", sa.Text, primary_key=True),
        sa.Column("date", sa.Date, primary_key=True),
        # §8.1 market model
        sa.Column("alpha", sa.Numeric(18, 10)),
        sa.Column("beta", sa.Numeric(18, 10)),
        sa.Column("resid_sd", sa.Numeric(18, 10)),
        sa.Column("n_obs", sa.Integer),
        sa.Column("r2", sa.Numeric(12, 8)),
        sa.Column("quality", sa.Text, nullable=False),
        # §8.2 turnover baseline, in rupees — never share volume (R9)
        sa.Column("mean_log_turnover", sa.Numeric(18, 10)),
        sa.Column("sd_log_turnover", sa.Numeric(18, 10)),
        # §8.3 delivery baseline, on the logit scale
        sa.Column("mean_delivery_logit", sa.Numeric(18, 10)),
        sa.Column("sd_delivery_logit", sa.Numeric(18, 10)),
        # §8.4 extremes and liquidity
        sa.Column("high_52w", sa.Numeric(18, 4)),
        sa.Column("low_52w", sa.Numeric(18, 4)),
        sa.Column("adv_20d", sa.Numeric(24, 4)),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quality IN ('OK','DEGRADED')", name="ck_baselines_quality"),
    )
    op.create_index("ix_baselines_date", "baselines", ["date"])

    # ─── §9.1 Announcements ─────────────────────────────────────────────────
    # UNIQUE (content_hash) is the dedup: the same filing re-appears across
    # polls, and the hash is what makes re-polling idempotent.
    op.create_table(
        "announcements",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("schedule_iii", sa.Text),
        sa.Column("attachment_url", sa.Text),
        sa.Column("raw_json", postgresql.JSONB, nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        # `source` is not in the §9.1 column list, but §20 states that every
        # fact table carries source and ingested_at ("This is N2"), and R4
        # allows no exceptions. Reconciled in favour of the invariant: the
        # narrower listing is a table, the invariant is the law.
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("content_hash", name="uq_announcements_content_hash"),
        sa.CheckConstraint(
            "schedule_iii IS NULL OR schedule_iii IN ('A','B')",
            name="ck_announcements_schedule_iii",
        ),
    )
    # The §9.3 linking window looks back from a move to recent filings for that
    # symbol, so this is the hot path.
    op.create_index(
        "ix_announcements_symbol_filed_at",
        "announcements",
        ["symbol", sa.text("filed_at DESC")],
    )

    # ─── §11.6 Liquidity hysteresis ─────────────────────────────────────────
    # State memory is the whole point: one threshold would make a stock hovering
    # at the floor flicker between suppressed and active day to day.
    op.create_table(
        "symbol_liquidity_state",
        sa.Column("symbol", sa.Text, primary_key=True),
        sa.Column(
            "state", sa.Text, nullable=False, server_default=sa.text("'ACTIVE'")
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('ACTIVE','SUPPRESSED')", name="ck_symbol_liquidity_state_state"
        ),
    )

    # ─── §20 signal_events ──────────────────────────────────────────────────
    # The output of the pure signal engine. `inputs_hash` is invariant N1:
    # every displayed number must be recomputable from stored inputs.
    op.create_table(
        "signal_events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trading_date", sa.Date, nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True)),
        sa.Column("window_end", sa.DateTime(timezone=True)),
        sa.Column("family", sa.Text, nullable=False),
        sa.Column("classification", sa.Text, nullable=False),
        # Refractory sign-flip — §10.5.
        sa.Column("sign", sa.SmallInteger, nullable=False),
        sa.Column("pct_move", sa.Numeric(12, 6)),
        sa.Column("ar", sa.Numeric(18, 10)),
        sa.Column("sar", sa.Numeric(12, 6)),
        sa.Column("car", sa.Numeric(18, 10)),
        sa.Column("scar", sa.Numeric(12, 6)),
        sa.Column("turnover_z", sa.Numeric(12, 6)),
        sa.Column("delivery_z", sa.Numeric(12, 6)),
        sa.Column("delivery_pct", sa.Numeric(8, 5)),
        sa.Column("mpm_triggered", sa.Boolean),
        sa.Column("mpm_base_threshold", sa.Numeric(6, 3)),
        sa.Column("mpm_effective_threshold", sa.Numeric(6, 3)),
        sa.Column("band_hit", sa.Boolean),
        # Multi-filing resolution — §9.4.
        sa.Column("linked_announcement_ids", postgresql.ARRAY(sa.BigInteger)),
        sa.Column("explained_by_ca_id", sa.BigInteger),
        sa.Column("score_base", sa.Numeric(12, 6)),
        # FactBundle completeness — §4.2. A signal computed on partial facts is
        # labelled as such, never silently scored as if complete.
        sa.Column(
            "completeness", postgresql.ARRAY(sa.Text), nullable=False
        ),
        sa.Column("provisional", sa.Boolean, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("superseded_by", sa.Text, sa.ForeignKey("signal_events.id")),
        sa.Column("inputs_hash", sa.CHAR(64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sign IN (-1, 0, 1)", name="ck_signal_events_sign"),
    )
    # §20, verbatim: the partial index that serves the current, non-superseded
    # view of a symbol's signals.
    op.create_index(
        "ix_signal_events_symbol_as_of",
        "signal_events",
        ["symbol", sa.text("as_of DESC")],
        postgresql_where=sa.text("superseded_by IS NULL"),
    )
    # The Brief loads signals with as_of > acknowledged_through_ts (§13.5), and
    # retention sweeps by trading_date (§12.6).
    op.create_index("ix_signal_events_trading_date", "signal_events", ["trading_date"])
    op.create_index(
        "ix_signal_events_as_of",
        "signal_events",
        [sa.text("as_of DESC")],
        postgresql_where=sa.text("superseded_by IS NULL"),
    )

    # ─── §12 Users, watchlists, cursors ─────────────────────────────────────
    # One demo user, multi-user-capable schema — §2.1.
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text, unique=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Server-authoritative, with `version` bumped on every mutation for the
    # If-Match optimistic concurrency in §12.3.
    op.create_table(
        "watchlists",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.BigInteger, nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])

    # position_key is a fractional index — a lexicographically sortable string
    # so an insert between two items needs no reindexing. POSITION_KEY_MAX_LEN
    # (=32) triggers the §12.3 background rebalance; it is not enforced as a
    # column width, because exceeding it schedules work rather than failing a
    # user's insert.
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "watchlist_id",
            sa.BigInteger,
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("position_key", sa.Text, nullable=False),
        # The §13.3 personal-multiplier inputs.
        sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
        sa.Column("holding", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
        sa.Column("level_price", sa.Numeric(18, 4)),
        sa.Column("level_set_at", sa.DateTime(timezone=True)),
        sa.Column("last_opened_at", sa.DateTime(timezone=True)),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_items_symbol"),
    )
    op.create_index(
        "ix_watchlist_items_order", "watchlist_items", ["watchlist_id", "position_key"]
    )

    # §12.1. Merged with max, nothing else — a join-semilattice, so concurrent
    # updates from two devices converge regardless of arrival order.
    op.create_table(
        "read_cursors",
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("scope_type", sa.Text, primary_key=True),
        sa.Column("scope_id", sa.Text, primary_key=True),
        sa.Column("seen_through_ts", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_through_ts", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_device_id", sa.Text),
        sa.CheckConstraint(
            "scope_type IN ('SYMBOL','WATCHLIST','GLOBAL')",
            name="ck_read_cursors_scope_type",
        ),
    )

    # §13.5 step 10: the full funnel counts for every Brief served. This is
    # what the §18.2 funnel chart is computed from, and it is why the eval
    # harness needs no separate instrumentation.
    op.create_table(
        "digest_deliveries",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cursor_ts", sa.DateTime(timezone=True)),
        sa.Column("candidates", sa.Integer, nullable=False),
        sa.Column("suppressed_corporate_action", sa.Integer, nullable=False),
        sa.Column("rolled_up_market_wide", sa.Integer, nullable=False),
        sa.Column("rolled_up_sector_wide", sa.Integer, nullable=False),
        sa.Column("suppressed_liquidity", sa.Integer, nullable=False),
        sa.Column("ranked", sa.Integer, nullable=False),
        sa.Column("surfaced", sa.Integer, nullable=False),
        sa.Column("quiet_count", sa.Integer, nullable=False),
        sa.Column("signal_event_ids", postgresql.ARRAY(sa.Text)),
        # N3: rendering more than BRIEF_MAX_ITEMS scored items is a P0 bug.
        # The cap is asserted by a property test; the database refuses to record
        # a delivery that broke it, so a violation cannot pass silently.
        sa.CheckConstraint(
            f"surfaced <= {BRIEF_MAX_ITEMS}", name="ck_digest_deliveries_brief_cap"
        ),
        sa.CheckConstraint("surfaced <= ranked", name="ck_digest_deliveries_funnel"),
    )
    op.create_index(
        "ix_digest_deliveries_user", "digest_deliveries", ["user_id", "delivered_at"]
    )

    # §18.5 the self-audit: the record of what the system surfaced that, on
    # inspection, it probably should not have.
    op.create_table(
        "signal_feedback",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "signal_event_id",
            sa.Text,
            sa.ForeignKey("signal_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("verdict", sa.Text, nullable=False),
        sa.Column("note", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "verdict IN ('USEFUL','NOT_USEFUL','WRONG')", name="ck_signal_feedback_verdict"
        ),
    )
    op.create_index(
        "ix_signal_feedback_signal_event", "signal_feedback", ["signal_event_id"]
    )


def downgrade() -> None:
    # Reverse dependency order, so every FK is gone before its target.
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    for table in (
        "signal_feedback",
        "digest_deliveries",
        "read_cursors",
        "watchlist_items",
        "watchlists",
        "users",
        "signal_events",
        "symbol_liquidity_state",
        "announcements",
        "baselines",
        "symbol_adjustment_factors",
        "delivery_stats",
        "index_snapshots_0930",
        "index_bars",
        "daily_bars",
        "ingest_quarantine",
        "ingest_runs",
        "corporate_actions",
        "trading_calendar",
        "symbol_master_snapshots",
        "symbol_aliases",
        "instruments",
    ):
        if table in existing_tables:
            op.drop_table(table)
