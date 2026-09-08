"""Announcement category resolution — docs/BUILD_SPEC.md §9.2.

Only `resolve_category` exists yet; the ingest itself is BUILD_PLAN task 2.8.
These tests are the regex table's own regression suite, anchored on the exact
failure the review found in revision 1's substring matching.
"""

from __future__ import annotations

from datetime import datetime

from app.ingest import announcements as ann
from app.ingest.announcement_ingest import content_hash, parse_announcements


def resolve(subject: str, desc: str | None = None) -> ann.Resolution:
    return ann.resolve_category(desc=desc, subject=subject)


# ─── The revision-1 bug the anchored patterns exist to fix ──────────────────


def test_download_does_not_match_loa():
    """Revision 1's substring match let "loa" match "Download". \\bloa\\b does
    not, because there is no word boundary inside "Download"."""
    result = resolve("Company has made available the Annual Report for Download")
    assert result.category != "ORDER_WIN"


def test_unconditional_does_not_match_ncd():
    """"ncd" as a substring matches "Unconditional"; \\bncd\\b does not."""
    result = resolve("Board approves Unconditional waiver of dues")
    assert result.category != "FUND_RAISE"


def test_reorder_does_not_match_order():
    result = resolve("Company to Reorder its manufacturing process")
    assert result.category not in ("ORDER_WIN", "MNA")


def test_in_order_to_does_not_match_order():
    result = resolve("Filed in order to comply with regulatory requirements")
    assert result.category != "ORDER_WIN"


# ─── Each category's real trigger phrase ────────────────────────────────────


def test_results_category():
    r = resolve("Outcome of Board Meeting - Unaudited Financial Results")
    assert r.category in ("RESULTS", "BOARD_MEETING")  # board meeting matches first
    assert r.schedule_iii == "A"


def test_results_alone():
    r = resolve("Submission of Audited Financial Results for the quarter")
    assert r.category == "RESULTS"


def test_board_meeting_category():
    assert resolve("Intimation of Board Meeting").category == "BOARD_MEETING"


def test_corp_action_category():
    for subject in (
        "Recommendation of Dividend",
        "Board approves Bonus Issue of equity shares",
        "Sub-Division of face value shares",
        "Buy-back of equity shares",
    ):
        assert resolve(subject).category == "CORP_ACTION"


def test_mna_category():
    for subject in (
        "Scheme of Arrangement for Amalgamation",
        "Proposed Merger with a subsidiary",
        "Acquisition of 100% stake",
    ):
        assert resolve(subject).category == "MNA"


def test_fund_raise_category():
    for subject in (
        "Allotment pursuant to Preferential Issue",
        "Approval for QIP",
        "Issuance of Non-Convertible Debenture",  # singular, matching the §9.2 pattern literally
        "Proposed Rights Issue of equity shares",
    ):
        assert resolve(subject).category == "FUND_RAISE"


def test_rating_category():
    for subject in (
        "CRISIL Ratings reaffirms rating",
        "ICRA assigns credit rating",
        "Rating Action on bank facilities",
    ):
        assert resolve(subject).category == "RATING"


def test_kmp_change_category():
    for subject in (
        "Resignation of Independent Director",
        "Appointment of Managing Director",
        "Cessation of directorship",
    ):
        assert resolve(subject).category == "KMP_CHANGE"


def test_litigation_category():
    for subject in (
        "Receipt of Show Cause Notice",
        "Order from NCLT",
        "Update on pending Litigation",
    ):
        assert resolve(subject).category == "LITIGATION"


def test_order_win_category():
    for subject in (
        "Receipt of Letter of Award for a new project",
        "Company bagged a new contract",
        "Order Received from a government body",
    ):
        r = resolve(subject)
        assert r.category == "ORDER_WIN"
        assert r.schedule_iii == "B"


def test_an_unrecognised_subject_is_other():
    r = resolve("Newspaper Publication of Notice of Annual General Meeting")
    assert r.category == "OTHER"
    assert r.schedule_iii is None
    assert r.source == ann.FROM_OTHER


def test_matching_is_case_insensitive():
    assert resolve("DIVIDEND RECOMMENDATION").category == "CORP_ACTION"
    assert resolve("dividend recommendation").category == "CORP_ACTION"


def test_first_match_wins_in_the_stated_order():
    """"Results" precedes "corp action" in CATEGORY_PATTERNS. A subject naming
    both should land on the earlier entry."""
    r = resolve("Financial Results along with Dividend Recommendation")
    assert r.category == "RESULTS"


# ─── The three-step resolution order ─────────────────────────────────────────


def test_a_desc_hit_is_authoritative_over_the_subject():
    """§9.2 step 1 beats step 2 even when the subject text would suggest a
    different category — the exchange's own field wins."""
    ann.CATEGORY_FROM_DESC["CREDIT RATING"] = "RATING"
    try:
        r = ann.resolve_category(
            desc="Credit Rating", subject="Company announces a new Bonus Issue"
        )
        assert r.category == "RATING"
        assert r.source == ann.FROM_DESC
    finally:
        ann.CATEGORY_FROM_DESC.clear()


def test_desc_lookup_is_normalised():
    ann.CATEGORY_FROM_DESC["FINANCIAL RESULTS"] = "RESULTS"
    try:
        r = ann.resolve_category(desc="  financial   results  ", subject="x")
        assert r.category == "RESULTS"
    finally:
        ann.CATEGORY_FROM_DESC.clear()


def test_an_unmapped_desc_falls_through_to_the_regex():
    """The table starts empty (task 2.8 populates it), so every real
    announcement today resolves at step 2 or 3."""
    assert ann.CATEGORY_FROM_DESC == {}
    r = ann.resolve_category(desc="Credit Rating", subject="ICRA assigns rating")
    assert r.category == "RATING"
    assert r.source == ann.FROM_REGEX


def test_a_missing_desc_goes_straight_to_the_subject():
    r = ann.resolve_category(desc=None, subject="Appointment of Managing Director")
    assert r.category == "KMP_CHANGE"


def test_an_empty_desc_is_treated_as_absent():
    r = ann.resolve_category(desc="", subject="Appointment of Managing Director")
    assert r.category == "KMP_CHANGE"


# ─── Source tagging, which the coverage report buckets on ──────────────────


def test_every_source_tag_is_one_of_three():
    for subject in ("Dividend Recommendation", "Random unrelated text", ""):
        assert resolve(subject).source in (ann.FROM_DESC, ann.FROM_REGEX, ann.FROM_OTHER)


def test_other_is_the_only_category_tagged_from_other():
    for _, schedule_iii, pattern in ann.CATEGORY_PATTERNS:
        del schedule_iii, pattern
    r = resolve("completely unrelated administrative filing")
    assert r.category == "OTHER"
    assert r.source == ann.FROM_OTHER


def test_categories_are_never_tagged_other_when_matched_by_regex():
    r = resolve("Board approves Bonus Issue")
    assert r.category == "CORP_ACTION"
    assert r.source == ann.FROM_REGEX


def test_parse_and_hash_are_stable():
    payload = (
        '[{"symbol":"ABC","subject":"Dividend declared",'
        '"filed_at":"2026-09-04T10:00:00+05:30","desc":"Dividend"}]'
    )
    parsed = parse_announcements(payload)
    assert parsed[0].symbol == "ABC"
    assert parsed[0].content_hash == content_hash(
        "ABC", "Dividend declared", datetime.fromisoformat("2026-09-04T10:00:00+05:30")
    )


def test_parse_rejects_naive_filed_at():
    payload = (
        '[{"symbol":"ABC","subject":"Notice",'
        '"filed_at":"2026-09-04T10:00:00","desc":"Notice"}]'
    )
    import pytest

    with pytest.raises(ValueError):
        parse_announcements(payload)
