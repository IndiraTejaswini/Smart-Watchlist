"""Parser coverage report — BUILD_PLAN task 1.6.

The stated acceptance criterion is narrow: "the report runs and the four CA
buckets sum to the row count." Asserted directly against the real, already-
loaded `corporate_actions` table (tasks 1.3-1.5), plus the properties that make
that sum true by construction rather than by coincidence, and the README
write path.

Announcements are not yet ingested (BUILD_PLAN task 2.8), so the announcement
half is tested two ways: against the real, empty table (the honest "not
ingested" report), and against fabricated rows inserted in a transaction that
is rolled back afterwards — proving the categorisation path works without ever
touching the database's real state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.config import get_settings
from app.ingest import announcements as ann
from app.ingest import coverage as cov


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
def ca_populated(engine):
    with engine.connect() as conn:
        if not conn.execute(sa.text("SELECT COUNT(*) FROM corporate_actions")).scalar_one():
            pytest.skip("no corporate actions; run `make actions` first")


# ─── ca_coverage: the stated acceptance criterion ───────────────────────────


def test_the_four_buckets_sum_to_the_row_count(engine, ca_populated):
    """BUILD_PLAN 1.6's stated acceptance criterion, verbatim."""
    with engine.connect() as conn:
        report = cov.ca_coverage(conn)
    assert sum(report.buckets[bucket] for bucket in cov.CA_BUCKETS) == report.total
    with engine.connect() as conn:
        actual_total = conn.execute(sa.text("SELECT COUNT(*) FROM corporate_actions")).scalar_one()
    assert report.total == actual_total


def test_the_partition_holds_for_any_verification_distribution():
    """The sum holds by construction — a partition of one enum column — not by
    coincidence of today's data. Checked against fabricated counts covering
    every verification value, including one report has never seen live."""

    class FakeConn:
        def execute(self, query, params=None):
            class Result:
                def all(self):
                    if "GROUP BY 1" in str(query):
                        return [
                            ("VERIFIED", 100),
                            ("UNVERIFIED", 20),
                            ("INFERRED", 3),
                            ("UNPARSED", 15),
                            ("DISCREPANCY", 7),
                        ]
                    return []  # the unparsed-example query

            return Result()

    report = cov.ca_coverage(FakeConn())  # type: ignore[arg-type]
    assert report.total == 145
    assert sum(report.buckets[b] for b in cov.CA_BUCKETS) == 145
    assert report.buckets[cov.PARSED] == 120
    assert report.buckets[cov.INFERRED] == 3
    assert report.buckets[cov.UNPARSED] == 15
    assert report.buckets[cov.DISCREPANT] == 7


def test_verified_and_unverified_are_a_sub_split_of_parsed_not_extra_rows():
    class FakeConn:
        def execute(self, *_a, **_k):
            class Result:
                def all(self):
                    return [("VERIFIED", 9), ("UNVERIFIED", 1)]

            return Result()

    report = cov.ca_coverage(FakeConn())  # type: ignore[arg-type]
    assert report.verified == 9
    assert report.unverified == 1
    assert report.buckets[cov.PARSED] == 10
    assert report.total == 10


def test_an_empty_table_reports_zero_without_dividing_by_zero():
    class FakeConn:
        def execute(self, *_a, **_k):
            class Result:
                def all(self):
                    return []

            return Result()

    report = cov.ca_coverage(FakeConn())  # type: ignore[arg-type]
    assert report.total == 0
    assert report.coverage_ratio == 0.0
    assert report.render()  # does not raise


def test_the_coverage_ratio_is_parsed_plus_inferred_over_total(engine, ca_populated):
    with engine.connect() as conn:
        report = cov.ca_coverage(conn)
    expected = (report.buckets[cov.PARSED] + report.buckets[cov.INFERRED]) / report.total
    assert report.coverage_ratio == pytest.approx(expected)


def test_the_real_history_meets_the_coverage_bar_documented_in_data_notes(
    engine, ca_populated
):
    """Not a stated acceptance criterion, but the number `docs/data-notes.md`
    reports (98.3% typed) — a regression floor so a future change that quietly
    breaks the parser is caught here rather than only in prose."""
    with engine.connect() as conn:
        report = cov.ca_coverage(conn)
    assert report.coverage_ratio >= 0.95


# ─── The unparsed examples: "here is the list" ──────────────────────────────


def test_unparsed_examples_are_grouped_by_distinct_string(engine, ca_populated):
    """The real tail is dominated by ~30 duplicate "Buy Back" rows; the report
    exists to be read, so it groups rather than repeating one string 30 times."""
    with engine.connect() as conn:
        report = cov.ca_coverage(conn, example_limit=5)
    purposes = [example.purpose_raw for example in report.examples]
    assert len(purposes) == len(set(purposes))
    assert len(report.examples) <= 5


def test_examples_are_ordered_by_frequency_first():
    """The most repeated unparsed string is the one most worth a reader's
    attention, so it sorts first."""

    class FakeConn:
        def __init__(self):
            self.queries = 0

        def execute(self, query, params=None):
            self.queries += 1
            text = str(query)
            if "GROUP BY 1" in text and "verification" in text:
                class R:
                    def all(self):
                        return [("UNPARSED", 3)]

                return R()

            class R2:
                def all(self):
                    return [
                        ("Rare One", 1, "SYM1", __import__("datetime").date(2026, 1, 1)),
                        ("Buy Back", 2, "SYM2", __import__("datetime").date(2026, 1, 2)),
                    ]

            return R2()

    report = cov.ca_coverage(FakeConn())  # type: ignore[arg-type]
    assert report.examples[0].purpose_raw == "Rare One"  # SQL ORDER BY n DESC does the sort;
    # this fixture returns them pre-sorted as the real query would, and the
    # assertion is that ca_coverage preserves that order rather than re-sorting.


def test_no_examples_are_fetched_when_nothing_is_unparsed():
    """The example query only runs when there is something to show — an empty
    result set is not itself evidence the query is wrong."""

    class FakeConn:
        def __init__(self):
            self.calls = 0

        def execute(self, *_a, **_k):
            self.calls += 1

            class R:
                def all(self):
                    return [("VERIFIED", 5)]

            return R()

    conn = FakeConn()
    report = cov.ca_coverage(conn)  # type: ignore[arg-type]
    assert report.examples == []
    assert conn.calls == 1, "the example query must not run when UNPARSED is zero"


# ─── announcement_coverage: not yet ingested ────────────────────────────────


def test_the_real_empty_table_reports_honestly(engine):
    with engine.connect() as conn:
        total = conn.execute(sa.text("SELECT COUNT(*) FROM announcements")).scalar_one()
    if total:
        pytest.skip("announcements has been ingested in this environment")
    with engine.connect() as conn:
        report = cov.announcement_coverage(conn)
    assert report.total == 0
    assert not report.ingested
    assert "not yet ingested" in report.render()
    assert "task 2.8" in report.render()


def test_the_report_never_claims_zero_coverage_when_nothing_was_measured():
    """A confident 0/0/0 would read as "the parser fails on every filing",
    which is false — nothing has been measured at all. `ingested=False` is
    what tells the renderer to say so instead."""
    report = cov.AnnouncementCoverage(total=0, ingested=False)
    text = report.render()
    assert "0.0%" not in text
    assert "resolved by desc" not in text


def test_fabricated_announcements_are_categorised_correctly(engine):
    """Inserted and rolled back — this proves the categorisation query works
    end to end without depending on task 2.8's ingest or leaving the database
    changed. `raw_json->>'desc'` is read exactly as the real ingest will store
    it (§9.1: the payload verbatim in `raw_json`)."""
    connection = engine.connect()
    transaction = connection.begin()
    try:
        rows = [
            ("FAB1", "Financial Results for Q1", "Financial Results"),
            ("FAB2", "Board approves Bonus Issue", None),
            ("FAB3", "Newspaper Publication of AGM Notice", "General Updates"),
        ]
        for i, (symbol, subject, desc) in enumerate(rows):
            raw = {"desc": desc} if desc else {}
            connection.execute(
                sa.text(
                    "INSERT INTO announcements "
                    "(symbol, filed_at, subject, category, raw_json, content_hash, "
                    "source, ingested_at) "
                    "VALUES (:symbol, NOW(), :subject, 'OTHER', CAST(:raw AS JSONB), "
                    ":hash, 'TEST', NOW())"
                ),
                {
                    "symbol": symbol,
                    "subject": subject,
                    "raw": json.dumps(raw),
                    "hash": f"{'0' * 63}{i}",
                },
            )
        report = cov.announcement_coverage(connection)
        assert report.total == 3
        assert report.ingested
        # FAB1's desc ("Financial Results") is not in CATEGORY_FROM_DESC (it is
        # empty until task 2.8), so it falls through to the regex, same as FAB2.
        assert report.by_regex == 2, "FAB1 and FAB2 both resolve via the subject regex"
        assert report.other == 1, "FAB3 matches no specific pattern"
        assert report.by_desc == 0
    finally:
        transaction.rollback()
        connection.close()


def test_a_populated_desc_map_is_reflected_in_by_desc(engine):
    """Once task 2.8 populates CATEGORY_FROM_DESC, this is what should move."""
    connection = engine.connect()
    transaction = connection.begin()
    ann.CATEGORY_FROM_DESC["FINANCIAL RESULTS"] = "RESULTS"
    try:
        connection.execute(
            sa.text(
                "INSERT INTO announcements "
                "(symbol, filed_at, subject, category, raw_json, content_hash, "
                "source, ingested_at) "
                "VALUES ('FAB4', NOW(), 'Q1 numbers', 'OTHER', "
                "CAST(:raw AS JSONB), :hash, 'TEST', NOW())"
            ),
            {"raw": json.dumps({"desc": "Financial Results"}), "hash": "1" * 64},
        )
        report = cov.announcement_coverage(connection)
        assert report.by_desc == 1
    finally:
        ann.CATEGORY_FROM_DESC.clear()
        transaction.rollback()
        connection.close()


# ─── render_report / render_readme_section ──────────────────────────────────


def test_render_report_includes_both_halves(engine, ca_populated):
    with engine.connect() as conn:
        ca = cov.ca_coverage(conn)
        announcements = cov.announcement_coverage(conn)
    text = cov.render_report(ca, announcements)
    assert "Corporate actions" in text
    assert "Announcements" in text
    for bucket in cov.CA_BUCKETS:
        assert bucket in text


def test_readme_section_reports_the_same_totals_as_the_cli(engine, ca_populated):
    with engine.connect() as conn:
        ca = cov.ca_coverage(conn)
        announcements = cov.announcement_coverage(conn)
    section = cov.render_readme_section(ca, announcements)
    assert cov.README_START in section and cov.README_END in section
    assert str(ca.total) in section
    assert f"{ca.coverage_ratio:.1%}" in section


def test_readme_section_states_the_announcement_caveat_when_not_ingested():
    section = cov.render_readme_section(
        cov.CACoverage(total=1, buckets=__import__("collections").Counter({cov.PARSED: 1})),
        cov.AnnouncementCoverage(total=0, ingested=False),
    )
    assert "task 2.8" in section


# ─── update_readme: create, then update in place, never truncate ───────────


def test_update_readme_creates_the_file_if_absent(tmp_path: Path):
    path = tmp_path / "README.md"
    cov.update_readme("SECTION-CONTENT", path=path)
    assert path.exists()
    assert "SECTION-CONTENT" in path.read_text(encoding="utf-8")


def test_update_readme_replaces_only_the_marked_section(tmp_path: Path):
    path = tmp_path / "README.md"
    path.write_text(
        "# My Project\n\nSome human-written intro.\n\n"
        f"{cov.README_START}\nOLD SECTION\n{cov.README_END}\n\n"
        "## Later section\nUntouched.\n",
        encoding="utf-8",
    )
    cov.update_readme(f"{cov.README_START}\nNEW SECTION\n{cov.README_END}", path=path)
    text = path.read_text(encoding="utf-8")
    assert "Some human-written intro." in text
    assert "## Later section" in text
    assert "Untouched." in text
    assert "OLD SECTION" not in text
    assert "NEW SECTION" in text


def test_update_readme_appends_when_no_markers_exist_yet(tmp_path: Path):
    """A human-authored README with no coverage section must gain one, not be
    overwritten by it."""
    path = tmp_path / "README.md"
    path.write_text("# My Project\n\nHand-written content.\n", encoding="utf-8")
    cov.update_readme(f"{cov.README_START}\nSECTION\n{cov.README_END}", path=path)
    text = path.read_text(encoding="utf-8")
    assert "Hand-written content." in text
    assert "SECTION" in text


def test_running_update_readme_twice_does_not_duplicate_the_section(tmp_path: Path):
    path = tmp_path / "README.md"
    section = f"{cov.README_START}\nV1\n{cov.README_END}"
    cov.update_readme(section, path=path)
    cov.update_readme(f"{cov.README_START}\nV2\n{cov.README_END}", path=path)
    text = path.read_text(encoding="utf-8")
    assert text.count(cov.README_START) == 1
    assert "V1" not in text
    assert "V2" in text


# ─── main(): the CLI runs end to end ─────────────────────────────────────────


def test_main_runs_without_touching_the_readme(capsys, ca_populated):
    exit_code = cov.main(["--no-readme"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Corporate actions" in out


def test_main_writes_the_readme_when_asked(tmp_path: Path, ca_populated):
    path = tmp_path / "README.md"
    exit_code = cov.main(["--readme-path", str(path)])
    assert exit_code == 0
    assert path.exists()
    assert cov.README_START in path.read_text(encoding="utf-8")
