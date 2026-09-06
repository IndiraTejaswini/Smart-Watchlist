"""CA factor inference for the unparsed tail — BUILD_PLAN task 1.5, §5.3.

Written before the implementation, with every snap computed by hand (R11).

§5.3 frames this as verification run backwards. Verification parses first and
then checks against the ex-date gap; inference starts from the gap when the text
failed. The result is two independent estimators of one quantity — the text and
the price — and this file is about the case where only the second exists.

The guard is the whole safety argument, and it is asserted in both directions:

> Without that guard a genuine -50% crash would be silently reinterpreted as a
> 1:1 bonus, which is the worst failure this system can produce. With it, we are
> only choosing *which* clean ratio applies to an action we already know
> happened.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.config import get_settings
from app.constants import CA_INFER_SNAP_TOLERANCE
from app.ingest import ca_infer, ca_verify
from app.ingest.calendar import earliest_cached_session

SNAP_TOLERANCE = Decimal(str(CA_INFER_SNAP_TOLERANCE))


# ─── snap_factor: the lookup table, not a parser ────────────────────────────


def test_an_exact_clean_factor_snaps_to_itself():
    result = ca_infer.snap_factor(Decimal("0.5"))
    assert result.verification == ca_infer.INFERRED
    assert result.price_factor == Decimal("0.5")
    assert result.distance == Decimal("0")


@pytest.mark.parametrize(
    ("gap", "expected"),
    [
        (Decimal("0.505"), Decimal("0.5")),  # +1.0% — a 1:1 bonus
        (Decimal("0.498477"), Decimal("0.5")),  # ECLERX 2026-03-13, real
        (Decimal("0.202"), Decimal("0.2")),  # +1.0% — a 10->2 split
        (Decimal("0.2513"), Decimal("0.25")),  # +0.5% — a 3:1 bonus
        (Decimal("0.335"), Decimal("0.3333333333")),  # +0.5% — a 2:1 bonus
        (Decimal("0.6700"), Decimal("0.6666666667")),  # 1:2 bonus
        (Decimal("10.05"), Decimal("10")),  # a 1:10 consolidation
        (Decimal("2.01"), Decimal("2")),  # a 1:2 consolidation
    ],
)
def test_a_gap_within_tolerance_snaps_to_the_clean_ratio(gap, expected):
    result = ca_infer.snap_factor(gap)
    assert result.verification == ca_infer.INFERRED
    assert result.price_factor == expected


def test_a_gap_outside_tolerance_does_not_snap():
    """0.52 is 4% away from 0.5, twice CA_INFER_SNAP_TOLERANCE. Left UNPARSED
    and suppressed — the band is deliberately tight because the cost of
    inventing a factor is a phantom crash."""
    result = ca_infer.snap_factor(Decimal("0.52"))
    assert result.verification == ca_infer.UNPARSED
    assert result.price_factor is None
    assert result.snapped_to == Decimal("0.5"), "the nearest is still reported"
    assert result.distance == Decimal("0.04")


def test_the_tolerance_boundary_is_inclusive():
    """§5.3 writes the test as `<=`."""
    on_boundary = Decimal("0.5") * (Decimal(1) + SNAP_TOLERANCE)
    assert ca_infer.snap_factor(on_boundary).verification == ca_infer.INFERRED
    just_past = on_boundary + Decimal("0.0001")
    assert ca_infer.snap_factor(just_past).verification == ca_infer.UNPARSED


def test_a_gap_between_two_clean_factors_snaps_to_neither():
    """0.15 sits between 0.125 and 1/6, 10% from the nearer. A lookup table
    that always returned its closest entry would answer every gap."""
    result = ca_infer.snap_factor(Decimal("0.15"))
    assert result.verification == ca_infer.UNPARSED


def test_no_gap_near_one_can_be_inferred():
    """CA_CLEAN_FACTORS contains no 1.0, deliberately: "no adjustment" is not a
    ratio to be recovered from a price that barely moved. R1 — the entry is not
    added to make the tail smaller."""
    for gap in (Decimal("0.99"), Decimal("1.0"), Decimal("1.01")):
        assert ca_infer.snap_factor(gap).verification == ca_infer.UNPARSED


@pytest.mark.parametrize("gap", [None, Decimal("0"), Decimal("-0.5")])
def test_an_absent_or_impossible_gap_infers_nothing(gap):
    result = ca_infer.snap_factor(gap)
    assert result.verification == ca_infer.UNPARSED
    assert result.price_factor is None
    assert result.reason


def test_the_nearest_factor_is_measured_relatively_not_absolutely():
    """The table spans 0.1 to 10.0, so absolute distance would make every large
    gap look closest to 10.0. The test §5.3 applies is `observed / snapped - 1`,
    and the search uses the same measure so the two cannot disagree."""
    # 4.0 is absolutely nearer 5.0 (1.0) than 2.0 (2.0), but relatively nearer
    # 5.0 as well (0.20 vs 1.00) — a case where they agree.
    assert ca_infer.snap_factor(Decimal("4.0")).snapped_to == Decimal("5")
    # 0.9 is absolutely equidistant-ish but relatively nearest 0.8333333333.
    assert ca_infer.snap_factor(Decimal("0.9")).snapped_to == Decimal("0.8333333333")


def test_every_clean_factor_is_reachable():
    """A factor in §21's table that nothing could ever snap to would be dead
    weight, and its absence from the results would look like a data property."""
    for factor in ca_infer.CLEAN_FACTORS:
        assert ca_infer.snap_factor(factor).price_factor == factor


# ─── Attribution across a composite ex-date ─────────────────────────────────


def test_a_sibling_with_a_known_factor_is_divided_out_first():
    """Task 1.4 established that one ex-date can carry several actions and that
    the market gaps by their product. Inferring the unknown one from the whole
    gap would attribute the entire move to it.

    A 1:1 bonus (0.5) plus an unreadable action, gapping to 0.25: the residual
    is 0.25 / 0.5 = 0.5, which is the unknown action's own factor.
    """
    result = ca_infer.infer_one(
        observed_gap=Decimal("0.25"), known_factor=Decimal("0.5"), unattributed=1
    )
    assert result.verification == ca_infer.INFERRED
    assert result.price_factor == Decimal("0.5")


def test_with_no_known_sibling_the_whole_gap_is_the_residual():
    result = ca_infer.infer_one(
        observed_gap=Decimal("0.505"), known_factor=None, unattributed=1
    )
    assert result.price_factor == Decimal("0.5")


def test_two_unreadable_actions_on_one_date_infer_nothing():
    """The residual is their product, and there is no way to say which half
    belongs to which. R6 — suppress rather than split it arbitrarily."""
    result = ca_infer.infer_one(
        observed_gap=Decimal("0.25"), known_factor=None, unattributed=2
    )
    assert result.verification == ca_infer.UNPARSED
    assert result.reason and "more than one" in result.reason


def test_a_known_sibling_of_zero_cannot_be_divided_out():
    result = ca_infer.infer_one(
        observed_gap=Decimal("0.25"), known_factor=Decimal("0"), unattributed=1
    )
    assert result.verification == ca_infer.UNPARSED


# ─── Against Postgres and the real loaded history ───────────────────────────


@pytest.fixture(scope="module")
def engine():
    engine = sa.create_engine(get_settings().database_url)
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
def window(engine, cache_root):
    with engine.connect() as conn:
        if not conn.execute(sa.text("SELECT COUNT(*) FROM corporate_actions")).scalar_one():
            pytest.skip("no corporate actions; run `make actions` first")
    return earliest_cached_session(cache_root), date.today() + timedelta(days=1)


# The stated acceptance case: a real, clean, single-action 1:1 bonus whose
# ex-date gap was 0.498477 — 0.3% from the clean 0.5.
MANGLED_CASE = ("ECLERX", date(2026, 3, 13))


def test_a_mangled_purpose_string_on_a_known_bonus_recovers_the_factor(
    engine, cache_root, window
):
    """The first stated acceptance criterion.

    The purpose string is deliberately destroyed in a transaction that is rolled
    back, so the assertion is made against the real row, the real ex-date and
    the real price gap rather than a fixture that could flatter the snap.
    """
    symbol, ex_date = MANGLED_CASE
    start, end = window
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT id, price_factor FROM corporate_actions "
                "WHERE symbol = :s AND ex_date = :d"
            ),
            {"s": symbol, "d": ex_date},
        ).first()
    if row is None:
        pytest.skip(f"{symbol} {ex_date} is not in this window")
    assert row.price_factor == Decimal("0.5000000000"), "the parsed factor, for contrast"

    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            sa.text(
                "UPDATE corporate_actions SET purpose_raw = :junk, action_type = 'UNPARSED', "
                "price_factor = NULL, tr_factor = NULL, verification = 'UNPARSED' "
                "WHERE id = :id"
            ),
            {"junk": "B0NU$ ###:### <<garbled>>", "id": row.id},
        )
        ca_infer.run(
            start=start,
            end=end,
            cache_root=cache_root,
            price_source="cache",
            conn=connection,
        )
        after = connection.execute(
            sa.text(
                "SELECT price_factor, verification FROM corporate_actions WHERE id = :id"
            ),
            {"id": row.id},
        ).one()
        assert after.price_factor == Decimal("0.5000000000")
        assert after.verification == ca_infer.INFERRED
    finally:
        transaction.rollback()
        connection.close()


def test_the_recovered_row_is_flagged_everywhere_it_appears(engine):
    """§5.3: INFERRED is "usable, but flagged everywhere it appears". It is a
    distinct verdict, never folded into VERIFIED."""
    assert ca_infer.INFERRED != ca_verify.VERIFIED
    assert ca_verify.is_trustworthy(ca_infer.INFERRED)


# ─── The guard: never infer an action from a price gap alone ────────────────


CRASH = ("__NOACTION__", date(2026, 3, 13))


def test_a_crash_with_no_scheduled_action_is_left_alone(engine, cache_root, window):
    """The second stated acceptance criterion, and the one that matters most.

    A -48% single-day fall on a date with no corporate action must stay
    unmodified. Nothing here reads a price gap for a symbol-date that has no
    row, so the guard is structural rather than a check that could be forgotten:
    inference iterates over scheduled actions and asks what factor they had, and
    never over price gaps asking whether an action occurred.
    """
    symbol, day = CRASH
    start, end = window
    with engine.connect() as conn:
        assert ca_infer.actions_on(conn, symbol, day) == []
        before = conn.execute(sa.text("SELECT COUNT(*) FROM corporate_actions")).scalar_one()

    ca_infer.run(start=start, end=end, cache_root=cache_root, price_source="cache", engine=engine)

    with engine.connect() as conn:
        after = conn.execute(sa.text("SELECT COUNT(*) FROM corporate_actions")).scalar_one()
        assert conn.execute(
            sa.text("SELECT COUNT(*) FROM corporate_actions WHERE symbol = :s"),
            {"s": symbol},
        ).scalar_one() == 0
    assert after == before, "inference never creates a row"


def test_a_gap_that_would_snap_cleanly_still_creates_nothing(engine, cache_root, window):
    """The stated -48% case is also outside the snap band, so on its own it
    would prove only that the tolerance held. This asserts the stronger thing:
    a -49.5% fall snaps to 0.5 perfectly well, and is still not turned into an
    action, because no row exists to attach it to."""
    assert ca_infer.snap_factor(Decimal("0.505")).verification == ca_infer.INFERRED
    with engine.connect() as conn:
        assert ca_infer.actions_on(conn, "__NOACTION__", date(2026, 3, 13)) == []


def test_the_stated_forty_eight_percent_fall_does_not_even_snap():
    """-48% is a gap of 0.52, which is 4% from the nearest clean factor against
    a 2% band. Two independent reasons it cannot become a bonus."""
    assert ca_infer.snap_factor(Decimal("0.52")).verification == ca_infer.UNPARSED


def test_inference_only_ever_touches_rows_that_were_already_unparsed(
    engine, cache_root, window
):
    """A verified factor is evidence from two sources agreeing. Inference must
    never overwrite one with a snapped guess."""
    start, end = window
    with engine.connect() as conn:
        before = dict(
            conn.execute(
                sa.text(
                    "SELECT id, price_factor FROM corporate_actions "
                    "WHERE verification = 'VERIFIED'"
                )
            ).all()
        )
    ca_infer.run(start=start, end=end, cache_root=cache_root, price_source="cache", engine=engine)
    with engine.connect() as conn:
        after = dict(
            conn.execute(
                sa.text(
                    "SELECT id, price_factor FROM corporate_actions "
                    "WHERE verification IN ('VERIFIED', 'INFERRED')"
                )
            ).all()
        )
    for row_id, factor in before.items():
        assert after[row_id] == factor


def test_the_run_reports_what_it_recovered_and_what_it_could_not(engine, cache_root, window):
    start, end = window
    report = ca_infer.run(
        start=start, end=end, cache_root=cache_root, price_source="cache", engine=engine
    )
    assert report.candidates > 0
    assert report.inferred + report.still_unparsed == report.candidates
    assert sum(report.reasons.values()) == report.still_unparsed


def test_no_inferred_row_lacks_the_gap_it_was_inferred_from(engine):
    """N2: no bare number. An inferred factor without its observed gap cannot be
    re-checked by a human, which is the point of flagging it."""
    with engine.connect() as conn:
        missing = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE verification = 'INFERRED' AND (observed_gap IS NULL OR price_factor IS NULL)"
            )
        ).scalar_one()
    assert missing == 0


def test_every_inferred_factor_is_one_of_the_clean_ratios(engine):
    """It is a lookup table, not a parser (§5.3). A value outside it would mean
    something computed a factor rather than choosing one."""
    with engine.connect() as conn:
        factors = conn.execute(
            sa.text(
                "SELECT DISTINCT price_factor FROM corporate_actions "
                "WHERE verification = 'INFERRED'"
            )
        ).scalars().all()
    assert set(factors) <= set(ca_infer.CLEAN_FACTORS)


def test_a_re_parse_cannot_strip_an_inferred_factor(engine, cache_root, window):
    """Regression. Task 1.3's upsert preserved the INFERRED verdict but took
    `price_factor` from the freshly parsed row — which for a rights issue or a
    demerger is NULL. The row kept asserting a factor it no longer held.

    Found by this file's own invariants after a full-suite run, on eight real
    rows. An inferred factor cannot be reproduced by re-reading the text, so a
    re-parse has nothing better to offer and must leave it alone.
    """
    from app.ingest import corporate_actions

    start, end = window
    ca_infer.run(start=start, end=end, cache_root=cache_root, price_source="cache", engine=engine)
    with engine.connect() as conn:
        before = dict(
            conn.execute(
                sa.text(
                    "SELECT id, price_factor FROM corporate_actions "
                    "WHERE verification = 'INFERRED'"
                )
            ).all()
        )
    if not before:
        pytest.skip("nothing was inferred in this window")

    corporate_actions.load(
        as_of=date.today(), from_cache_only=True, cache_root=cache_root, engine=engine
    )
    with engine.connect() as conn:
        after = dict(
            conn.execute(
                sa.text(
                    "SELECT id, price_factor FROM corporate_actions "
                    "WHERE verification = 'INFERRED'"
                )
            ).all()
        )
    assert after == before


def test_no_row_asserts_a_verdict_it_cannot_show_the_number_for(engine):
    """The general form of the same defect: any verdict claiming a factor must
    have one. This is the invariant that caught it."""
    with engine.connect() as conn:
        broken = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE verification IN ('VERIFIED', 'INFERRED') AND price_factor IS NULL"
            )
        ).scalar_one()
    assert broken == 0


def test_inference_only_ever_fills_an_absent_factor(engine, cache_root, window):
    """It can never replace one. A factor already present came either from the
    text or from two sources agreeing, and both outrank a snapped guess."""
    start, end = window
    with engine.connect() as conn:
        before = dict(
            conn.execute(
                sa.text(
                    "SELECT id, price_factor FROM corporate_actions "
                    "WHERE price_factor IS NOT NULL"
                )
            ).all()
        )
    ca_infer.run(start=start, end=end, cache_root=cache_root, price_source="cache", engine=engine)
    with engine.connect() as conn:
        after = dict(
            conn.execute(
                sa.text(
                    "SELECT id, price_factor FROM corporate_actions "
                    "WHERE id = ANY(CAST(:ids AS bigint[]))"
                ),
                {"ids": list(before)},
            ).all()
        )
    assert after == before
