"""`/api/eval/unparsed-actions` — BUILD_PLAN task 1.4, ARCHITECTURE.md §16.

The second half of task 1.4's acceptance: "every DISCREPANCY is listed at
/api/eval/unparsed-actions". Also the end-to-end check on the verification job
itself, since the endpoint reads what the job wrote.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import get_settings
from app.ingest import ca_verify
from app.ingest.calendar import earliest_cached_session
from app.main import create_app

# §1.4: ">= 85% of parsed actions as VERIFIED", over the backfilled history.
MINIMUM_VERIFIED_RATIO = 0.85


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
def verified(engine, cache_root):
    """Run the job over the whole backfilled history, as the criterion says."""
    start = earliest_cached_session(cache_root)
    with engine.connect() as conn:
        actions = conn.execute(sa.text("SELECT COUNT(*) FROM corporate_actions")).scalar_one()
    if not actions:
        pytest.skip("no corporate actions; run `make actions` first")
    return ca_verify.run(
        start=start,
        end=date.today() + timedelta(days=1),
        cache_root=cache_root,
        price_source="cache",
        engine=engine,
    )


@pytest.fixture(scope="module")
def client(verified):
    with TestClient(create_app()) as test_client:
        yield test_client


# ─── The acceptance criterion ───────────────────────────────────────────────


def test_the_history_verifies_above_the_acceptance_bar(verified):
    """§1.4: at least 85% of the actions the market can settle."""
    assert verified.testable > 0
    assert verified.verified_ratio >= MINIMUM_VERIFIED_RATIO


def test_the_job_reports_which_price_source_it_used(verified):
    """A job that silently changed its evidence base between runs would make
    two different verdicts look like one."""
    assert "bhavcopy" in verified.price_source or "daily_bars" in verified.price_source


def test_composite_ex_dates_were_verified_as_events(verified):
    """The real history contains ex-dates carrying a bonus and a split at once.
    Verified singly they all fail; the count proves the grouping ran."""
    assert verified.composite_events > 0


def test_no_verdict_was_reached_on_an_unparsed_row(verified, engine):
    """An UNPARSED row has no factor to test. Task 1.5 recovers those, by a
    different route, and must find them still marked UNPARSED."""
    with engine.connect() as conn:
        leaked = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE action_type = 'UNPARSED' AND verification <> 'UNPARSED'"
            )
        ).scalar_one()
    assert leaked == 0


def test_verification_filled_the_tr_factors_left_null_by_task_1_3(verified, engine):
    """§5.3's tr_factor needs the previous close, which task 1.3 did not have.
    Verification is the first stage that does, so it completes the column."""
    assert verified.tr_factor_filled > 0
    with engine.connect() as conn:
        dividends_with_tr = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE action_type = 'DIVIDEND' AND tr_factor IS NOT NULL"
            )
        ).scalar_one()
    assert dividends_with_tr > 0


def test_a_dividends_tr_factor_is_below_one_and_its_price_factor_is_not(verified, engine):
    """The PRI/TRI split, seen from the other end: the price series is untouched
    by a dividend and the total-return series is not."""
    with engine.connect() as conn:
        wrong = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM corporate_actions WHERE action_type = 'DIVIDEND' "
                "AND tr_factor IS NOT NULL "
                "AND (price_factor <> 1.0 OR tr_factor > 1.0 OR tr_factor <= 0)"
            )
        ).scalar_one()
    assert wrong == 0


def test_every_verified_row_has_the_evidence_it_was_verified_on(verified, engine):
    """N2: no bare number. A verdict without its observed gap cannot be
    re-checked by a human, which is the whole point of storing it."""
    with engine.connect() as conn:
        missing = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE verification IN ('VERIFIED','DISCREPANCY') AND observed_gap IS NULL"
            )
        ).scalar_one()
    assert missing == 0


def test_an_absent_bar_leaves_a_row_unverified_not_discrepant(verified, engine):
    """Absence of evidence is not evidence of a parser error. InvIT and REIT
    units trade outside the §2.1 EQ/BE/BZ scope, so they have no bar to compare
    against and must not be branded discrepancies for it."""
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT verification FROM corporate_actions "
                "WHERE symbol = 'EMBASSY' AND action_type <> 'UNPARSED' LIMIT 1"
            )
        ).scalar()
    if row is None:
        pytest.skip("no EMBASSY action in this window")
    assert row == ca_verify.UNVERIFIED


# ─── The endpoint ───────────────────────────────────────────────────────────


def test_the_endpoint_serves_every_discrepancy(client, engine):
    """The stated criterion: every DISCREPANCY is listed."""
    response = client.get("/api/eval/unparsed-actions", params={"limit": 1000})
    assert response.status_code == 200
    listed = {
        (row["symbol"], row["ex_date"])
        for row in response.json()["items"]
        if row["verification"] == ca_verify.DISCREPANCY
    }
    with engine.connect() as conn:
        stored = {
            (symbol, ex_date.isoformat())
            for symbol, ex_date in conn.execute(
                sa.text(
                    "SELECT symbol, ex_date FROM corporate_actions "
                    "WHERE verification = 'DISCREPANCY'"
                )
            ).all()
        }
    assert stored <= listed


def test_the_endpoint_also_serves_the_unparsed_strings(client):
    """Both ways the same question is answered wrongly, in one place: the
    string that could not be read, and the factor the market contradicted."""
    body = client.get("/api/eval/unparsed-actions", params={"limit": 1000}).json()
    verdicts = {row["verification"] for row in body["items"]}
    assert verdicts <= {ca_verify.UNPARSED, ca_verify.DISCREPANCY}
    assert ca_verify.UNPARSED in verdicts


def test_every_listed_row_carries_the_text_that_produced_it(client):
    """§5.3.0's point: publishing what the parser could not read is a stronger
    position than claiming it always can. That needs the original string."""
    for row in client.get("/api/eval/unparsed-actions").json()["items"]:
        assert row["purpose_raw"]
        assert row["symbol"] and row["ex_date"]


def test_the_summary_reports_the_coverage_and_the_band(client, verified):
    body = client.get("/api/eval/unparsed-actions").json()
    summary = body["summary"]
    assert summary["corporate_actions"] > 0
    assert summary["verified_ratio"] == pytest.approx(verified.verified_ratio, abs=1e-4)
    assert summary["tolerance"] == pytest.approx(0.08)


def test_the_limit_is_bounded():
    """An unbounded list endpoint is a denial-of-service waiting to happen."""
    client = TestClient(create_app())
    assert client.get("/api/eval/unparsed-actions", params={"limit": 100_000}).status_code == 422
    assert client.get("/api/eval/unparsed-actions", params={"limit": 0}).status_code == 422


def test_the_openapi_schema_renders():
    """§9 will assert this properly; here it is a smoke test that the app is
    wired rather than merely importable."""
    body = TestClient(create_app()).get("/openapi.json").json()
    assert "/api/eval/unparsed-actions" in body["paths"]
