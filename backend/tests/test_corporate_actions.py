"""Corporate-action ingest — BUILD_PLAN task 1.3, docs/BUILD_SPEC.md §5.3.

The parser's own tests are in `test_ca_parser.py`. This file covers the write
path: what reaches `corporate_actions`, what is quarantined, and the invariant
that survives a re-run.

The third acceptance criterion — "every unparsed row is recorded, none silently
dropped" — is a property of this layer, not of the parser, so it is asserted
here in both halves: nothing is dropped in `build_rows`, and nothing is dropped
on the way into the database.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.config import get_settings
from app.ingest import ca_parser
from app.ingest import corporate_actions as ca
from app.ingest.calendar import earliest_cached_session

# ─── A feed payload shaped exactly like the real one ────────────────────────

FEED = json.dumps(
    [
        {
            "symbol": "PATANJALI",
            "comp": "Patanjali Foods Limited",
            "series": "EQ",
            "faceVal": "2",
            "isin": "INE619A01035",
            "subject": "Bonus 2:1",
            "exDate": "11-Sep-2025",
            "recDate": "11-Sep-2025",
            "bcStartDate": "-",
        },
        {
            "symbol": "RELIANCE",
            "series": "EQ",
            "subject": "Dividend - Rs 12 Per Share",
            "exDate": "20-Aug-2026",
            "recDate": "20-Aug-2026",
        },
        {
            "symbol": "SOMECO",
            "series": "EQ",
            "subject": "Scheme Of Arrangement - Bonus Ncrps 46:1",
            "exDate": "01-Jul-2026",
            "recDate": "-",
        },
        {
            "symbol": "RIGHTSCO",
            "series": "EQ",
            "subject": "Rights 1:2 @ Premium Rs 290/-",
            "exDate": "05-May-2026",
            "recDate": "05-May-2026",
        },
        {
            "symbol": "SPLITCO",
            "series": "EQ",
            "subject": (
                "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
            ),
            "exDate": "09-Jun-2026",
            "recDate": "09-Jun-2026",
        },
        # Rejected: no ex-date can be matched to a session (§4.3).
        {"symbol": "NODATE", "series": "EQ", "subject": "Bonus 1:1", "exDate": "-"},
        # Rejected: no symbol.
        {"symbol": "", "series": "EQ", "subject": "Bonus 1:1", "exDate": "01-Jul-2026"},
        # A duplicate of the first entry, as the feed sometimes repeats one.
        {
            "symbol": "PATANJALI",
            "series": "EQ",
            "subject": "Bonus 2:1",
            "exDate": "11-Sep-2025",
            "recDate": "11-Sep-2025",
        },
    ]
).encode()


def _rows():
    return ca.build_rows(ca.parse_feed(FEED))


# ─── parse_feed ─────────────────────────────────────────────────────────────


def test_the_feed_parses_from_a_bare_list():
    assert len(ca.parse_feed(FEED)) == 8


def test_the_feed_parses_from_a_data_wrapper():
    """NSE returns a bare list here and a {"data": [...]} envelope elsewhere.
    Both shapes are accepted rather than one being assumed."""
    wrapped = json.dumps({"data": [{"symbol": "X", "subject": "Bonus 1:1"}]}).encode()
    assert len(ca.parse_feed(wrapped)) == 1


def test_a_non_row_entry_is_ignored():
    assert ca.parse_feed(json.dumps(["junk", {"symbol": "X"}]).encode()) == [
        {"symbol": "X"}
    ]


# ─── build_rows ─────────────────────────────────────────────────────────────


def test_every_feed_row_is_either_written_or_quarantined():
    """The acceptance criterion, at this layer: none silently dropped.

    The one exception is the exact duplicate, which is the feed listing one
    action twice — the natural key cannot hold it twice by construction.
    """
    feed = ca.parse_feed(FEED)
    rows, rejected = ca.build_rows(feed)
    assert len(rows) + len(rejected) == len(feed) - 1


def test_a_row_without_an_ex_date_is_quarantined_with_its_reason():
    """§4.3 matches ex-dates on the IST trading date, so a row with no ex-date
    can never be matched to a session at all."""
    _, rejected = _rows()
    reasons = {row.reason for row in rejected}
    assert "MISSING_OR_UNPARSED_EX_DATE" in reasons
    assert all(row.payload for row in rejected)


def test_a_row_without_a_symbol_is_quarantined():
    _, rejected = _rows()
    assert "MISSING_REQUIRED_FIELD" in {row.reason for row in rejected}


def test_a_duplicate_feed_row_is_collapsed_not_duplicated():
    """UNIQUE (symbol, ex_date, action_type, purpose_raw) is the natural key."""
    rows, _ = _rows()
    keys = [(r.symbol, r.ex_date, r.action_type, r.purpose_raw) for r in rows]
    assert len(keys) == len(set(keys))


def test_dates_are_read_in_the_exchange_format():
    rows, _ = _rows()
    bonus = next(r for r in rows if r.symbol == "PATANJALI")
    assert bonus.ex_date == date(2025, 9, 11)
    assert bonus.record_date == date(2025, 9, 11)


def test_a_dash_record_date_is_absent_not_a_date():
    rows, _ = _rows()
    assert next(r for r in rows if r.symbol == "SOMECO").record_date is None


def test_the_parsed_factor_reaches_the_row():
    rows, _ = _rows()
    assert next(r for r in rows if r.symbol == "PATANJALI").price_factor == Decimal(
        "0.3333333333"
    )
    assert next(r for r in rows if r.symbol == "SPLITCO").price_factor == Decimal("0.2")


# ─── The PRI/TRI split ──────────────────────────────────────────────────────


def test_a_cash_dividend_is_written_with_price_factor_one():
    """R10 and the second acceptance criterion."""
    rows, _ = _rows()
    dividend = next(r for r in rows if r.symbol == "RELIANCE")
    assert dividend.action_type == ca_parser.DIVIDEND
    assert dividend.price_factor == Decimal(1)


def test_a_dividends_tr_factor_waits_for_a_previous_close():
    """§5.3 needs `prev` to compute it, and `daily_bars` is Phase 2. NULL, not
    a guess."""
    rows, _ = _rows()
    assert next(r for r in rows if r.symbol == "RELIANCE").tr_factor is None


def test_a_previous_close_completes_the_dividends_tr_factor():
    """The §5.3 worked example: ₹12 on ₹840 -> 0.9857142857."""
    rows, _ = ca.build_rows(
        ca.parse_feed(FEED),
        prev_close={("RELIANCE", date(2026, 8, 20)): Decimal("840")},
    )
    dividend = next(r for r in rows if r.symbol == "RELIANCE")
    assert dividend.price_factor == Decimal(1)
    assert dividend.tr_factor == Decimal("0.9857142857")


def test_a_bonus_tr_factor_needs_no_previous_close():
    """With no dividend term the two factors coincide, so it is knowable now."""
    rows, _ = _rows()
    bonus = next(r for r in rows if r.symbol == "PATANJALI")
    assert bonus.tr_factor == bonus.price_factor == Decimal("0.3333333333")


# ─── verification ───────────────────────────────────────────────────────────


def test_a_parsed_row_is_unverified_until_the_market_checks_it():
    """This task parses; task 1.4 verifies against the observed ex-date gap.
    Nothing here may claim VERIFIED."""
    rows, _ = _rows()
    assert next(r for r in rows if r.symbol == "PATANJALI").verification == ca.UNVERIFIED


def test_an_unreadable_row_is_marked_unparsed_and_suppressed():
    rows, _ = _rows()
    assert next(r for r in rows if r.symbol == "SOMECO").verification == ca.UNPARSED


def test_a_price_moving_action_with_no_factor_is_marked_unparsed():
    """A rights issue is typed but carries no factor, and §5.3's fail-safe rule
    suppresses it. Calling it UNVERIFIED would read as merely awaiting a check.
    """
    rows, _ = _rows()
    rights = next(r for r in rows if r.symbol == "RIGHTSCO")
    assert rights.action_type == ca_parser.RIGHTS
    assert rights.price_factor is None
    assert rights.verification == ca.UNPARSED


def test_no_row_this_task_writes_claims_to_be_verified():
    rows, _ = _rows()
    assert {r.verification for r in rows} <= {ca.UNVERIFIED, ca.UNPARSED}


# ─── The report ─────────────────────────────────────────────────────────────


def test_the_coverage_ratio_counts_typed_rows():
    report = ca.LoadReport(start=date(2026, 1, 1), end=date(2026, 3, 1), inputs_digest="x")
    rows, rejected = _rows()
    ca._fill_report(report, rows, rejected)
    typed = sum(1 for r in rows if r.action_type != ca_parser.UNPARSED)
    assert report.parse_coverage_ratio == pytest.approx(typed / len(rows))


def test_an_empty_report_does_not_divide_by_zero():
    assert (
        ca.LoadReport(
            start=date(2026, 1, 1), end=date(2026, 3, 1), inputs_digest="x"
        ).parse_coverage_ratio
        == 0.0
    )


def test_every_unparsed_row_carries_a_reason_into_the_report():
    """"None silently dropped" means the reason survives to the operator."""
    report = ca.LoadReport(start=date(2026, 1, 1), end=date(2026, 3, 1), inputs_digest="x")
    rows, rejected = _rows()
    ca._fill_report(report, rows, rejected)
    assert sum(report.unparsed_reasons.values()) == report.action_type_counts[
        ca_parser.UNPARSED
    ]
    assert all(reason != "unstated" for reason in report.unparsed_reasons)


def test_the_digest_covers_the_window_as_well_as_the_payloads():
    a = ca.inputs_digest({"c.json": FEED}, (date(2026, 1, 1), date(2026, 3, 1)))
    b = ca.inputs_digest({"c.json": FEED}, (date(2026, 1, 1), date(2026, 4, 1)))
    assert a != b


# ─── Against Postgres and the real loaded feed ──────────────────────────────


@pytest.fixture(scope="module")
def engine():
    engine = sa.create_engine(get_settings().database_url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001 — any connection failure is a skip
        pytest.skip(f"postgres unreachable ({type(exc).__name__}); run `make up`")
    return engine


@pytest.fixture(scope="module")
def cache_root():
    root = Path(get_settings().cache_root)
    if earliest_cached_session(root) is None:
        pytest.skip("no cached bhavcopy; run `make backfill` first")
    return root


@pytest.fixture(scope="module")
def loaded(engine, cache_root):
    return ca.load(
        as_of=date.today(), from_cache_only=True, cache_root=cache_root, engine=engine
    )


def test_the_real_feed_parses_above_the_acceptance_bar(loaded):
    """BUILD_PLAN 1.3 sets 90% on a 30-string fixture. Measured over every real
    row in the window, not a sample."""
    assert loaded.parse_coverage_ratio >= 0.90


def test_every_cash_dividend_in_the_database_has_price_factor_one(loaded, engine):
    """The acceptance criterion, asserted where it actually matters — R10 makes
    this the one number in the table that may never drift."""
    with engine.connect() as conn:
        wrong = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE action_type = 'DIVIDEND' AND price_factor IS DISTINCT FROM 1.0"
            )
        ).scalar_one()
    assert wrong == 0


def test_a_factor_on_a_non_price_moving_action_can_only_have_been_inferred(
    loaded, engine
):
    """Under PRI only splits, bonuses and consolidations move the price, so the
    *parser* may never give anything else a factor other than 1.0 — asserted on
    its own output in `test_ca_parser`.

    Task 1.5 may, and that is its purpose: a rights issue or a demerger states
    no factor in its text, and inference recovers one from the observed ex-date
    gap. So the database-level invariant is not that no such row exists, but
    that every one of them says where its number came from.
    """
    with engine.connect() as conn:
        offenders = conn.execute(
            sa.text(
                "SELECT symbol, action_type, verification FROM corporate_actions "
                "WHERE price_factor IS NOT NULL AND price_factor <> 1.0 "
                "AND action_type NOT IN ('BONUS','SPLIT','CONSOLIDATION','COMPOSITE') "
                "AND verification <> 'INFERRED'"
            )
        ).all()
    assert offenders == []


def test_no_factor_is_zero_or_negative(loaded, engine):
    """A non-positive factor turns a price into zero or a negative number."""
    with engine.connect() as conn:
        bad = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE price_factor IS NOT NULL AND price_factor <= 0"
            )
        ).scalar_one()
    assert bad == 0


def test_every_unparsed_row_is_recorded_rather_than_dropped(loaded, engine):
    """The third acceptance criterion, end to end: the rows the parser refused
    are in the table, typed UNPARSED, with their original text intact."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT purpose_raw, price_factor, verification FROM corporate_actions "
                "WHERE action_type = 'UNPARSED'"
            )
        ).all()
    assert len(rows) == loaded.action_type_counts[ca_parser.UNPARSED]
    assert all(row.purpose_raw for row in rows)
    assert all(row.price_factor is None for row in rows)
    assert all(row.verification == ca.UNPARSED for row in rows)


def test_the_non_equity_bonuses_are_in_the_table_and_carry_no_factor(loaded, engine):
    """The catastrophic string, checked where it would do the damage. Read as
    an equity bonus, "Bonus Ncrps 46:1" adjusts a price by 1/47."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT action_type, price_factor FROM corporate_actions "
                "WHERE purpose_raw ILIKE '%NCRPS%'"
            )
        ).all()
    assert rows, "the NCRPS rows must be recorded, not filtered out"
    assert all(row.action_type == ca_parser.UNPARSED for row in rows)
    assert all(row.price_factor is None for row in rows)


def test_every_action_type_satisfies_the_check_constraint(loaded, engine):
    with engine.connect() as conn:
        types = set(
            conn.execute(sa.text("SELECT DISTINCT action_type FROM corporate_actions")).scalars()
        )
    assert types <= set(ca_parser.ACTION_TYPES)


def test_every_stored_verdict_is_one_of_the_five_in_the_enum(loaded, engine):
    """§5.3's verification enum, as a database-level invariant.

    This deliberately does not assert that the table holds only what *this*
    task writes: task 1.4 settles rows against the ex-date gap and writes
    VERIFIED and DISCREPANCY into the same column. That this task never claims
    one itself is asserted on its own output, in
    `test_no_row_this_task_writes_claims_to_be_verified`.
    """
    with engine.connect() as conn:
        verdicts = set(
            conn.execute(sa.text("SELECT DISTINCT verification FROM corporate_actions")).scalars()
        )
    assert verdicts <= {"VERIFIED", "INFERRED", "DISCREPANCY", ca.UNVERIFIED, ca.UNPARSED}


def test_the_run_is_recorded_with_its_provenance(loaded, engine):
    """§6.2 rule 2 / R4."""
    with engine.connect() as conn:
        status, rows, file_hash = conn.execute(
            sa.text(
                "SELECT status, rows, file_hash FROM ingest_runs WHERE source = :s "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"s": ca.SOURCE},
        ).one()
    assert status in ("OK", "SKIPPED_CACHED")
    assert file_hash == loaded.inputs_digest
    assert rows > 0


def test_every_stored_row_carries_its_source_and_ingest_time(loaded, engine):
    with engine.connect() as conn:
        missing = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE source IS NULL OR ingested_at IS NULL"
            )
        ).scalar_one()
    assert missing == 0


def test_reloading_unchanged_inputs_changes_nothing(loaded, engine, cache_root):
    """§6.2 rules 1 and 3."""
    with engine.connect() as conn:
        before = conn.execute(sa.text("SELECT COUNT(*) FROM corporate_actions")).scalar_one()
    again = ca.load(
        as_of=date.today(), from_cache_only=True, cache_root=cache_root, engine=engine
    )
    with engine.connect() as conn:
        after = conn.execute(sa.text("SELECT COUNT(*) FROM corporate_actions")).scalar_one()
    assert before == after
    assert again.skipped_cached


def test_an_empirical_verdict_survives_a_re_parse(loaded, engine, cache_root):
    """Task 1.4 writes VERIFIED and DISCREPANCY from the observed ex-date gap.
    Re-running this task must not demote one back to UNVERIFIED, or the morning
    job's work would be undone by the next refresh."""
    with engine.begin() as conn:
        target = conn.execute(
            sa.text(
                "SELECT id FROM corporate_actions WHERE verification = 'UNVERIFIED' LIMIT 1"
            )
        ).scalar_one()
        conn.execute(
            sa.text("UPDATE corporate_actions SET verification = 'VERIFIED' WHERE id = :i"),
            {"i": target},
        )
        # A prior run for this digest exists, so force the write path to run.
        conn.execute(
            sa.text("UPDATE ingest_runs SET status = 'FAILED' WHERE source = :s"),
            {"s": ca.SOURCE},
        )
    ca.load(as_of=date.today(), from_cache_only=True, cache_root=cache_root, engine=engine)
    with engine.connect() as conn:
        after = conn.execute(
            sa.text("SELECT verification FROM corporate_actions WHERE id = :i"),
            {"i": target},
        ).scalar_one()
    assert after == "VERIFIED"
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE corporate_actions SET verification = 'UNVERIFIED' WHERE id = :i"),
            {"i": target},
        )
