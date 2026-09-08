"""Corporate-action purpose parser — BUILD_PLAN task 1.3, docs/BUILD_SPEC.md §5.3.

Written before the implementation, with every factor computed by hand (R11).
This is the one place in the system where a parse failure is catastrophic:
§5.3.0 rates it the only High-risk text parse, because a wrong factor renders a
phantom crash that never happened.

Every string in `fixtures/corporate_action_purposes.json` is a real NSE
`subject`, pulled from `/api/corporates-corporateActions` over 2025-09 to
2026-11 — 2,121 rows, 594 distinct strings. The three traps below are all real
findings from that data, not hypotheticals.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.ingest import ca_parser as p

FIXTURE = Path(__file__).parent / "fixtures" / "corporate_action_purposes.json"


def fixtures() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def factor(purpose: str) -> Decimal | None:
    return p.parse(purpose).price_factor


# ─── Bonus: factor = held / (new + held) ────────────────────────────────────
# "Bonus a:b" is a new shares for every b held, so one b-share holding becomes
# a + b shares. §5.3 fixes the reading: 1:1 -> 0.5 and 3:7 -> 0.7.


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        ("Bonus 1:1", Decimal("0.5")),  # 1/(1+1)
        ("Bonus 3:7", Decimal("0.7")),  # 7/(3+7) — the §5.3 worked example
        ("Bonus 2:1", Decimal("0.3333333333")),  # 1/3
        ("Bonus 3:1", Decimal("0.25")),  # 1/4
        ("Bonus 1:2", Decimal("0.6666666667")),  # 2/3
        ("Bonus 2:5", Decimal("0.7142857143")),  # 5/7
        ("Bonus 5:7", Decimal("0.5833333333")),  # 7/12
        ("Bonus 10:1", Decimal("0.0909090909")),  # 1/11
        ("Bonus 1:10", Decimal("0.9090909091")),  # 10/11
    ],
)
def test_bonus_factor(purpose, expected):
    assert factor(purpose) == expected


def test_a_bonus_is_typed_bonus_and_keeps_its_ratio():
    parsed = p.parse("Bonus 2:1")
    assert parsed.action_type == p.BONUS
    assert parsed.ratio_text == "2:1"


def test_a_bonus_factor_is_always_below_one():
    """A bonus issues shares, so the price can only fall. A factor above 1
    would mean the parser read the ratio backwards."""
    for purpose in ("Bonus 1:1", "Bonus 2:1", "Bonus 1:10", "Bonus 10:1"):
        value = factor(purpose)
        assert value is not None and Decimal(0) < value < Decimal(1)


# ─── Face-value split and consolidation: factor = to / from ─────────────────


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        ("FACE VALUE SPLIT FROM RS.10 TO RS.2", Decimal("0.2")),  # §5.3 example
        (
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share",
            Decimal("0.1"),
        ),
        (
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share",
            Decimal("0.2"),
        ),
        (
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 5/- Per Share",
            Decimal("0.5"),
        ),
        (
            "Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 1/- Per Share",
            Decimal("0.2"),
        ),
        (
            "Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share",
            Decimal("0.5"),
        ),
    ],
)
def test_split_factor(purpose, expected):
    assert factor(purpose) == expected


def test_consolidation_is_a_split_the_other_way():
    """§5.3: `CONSOLIDATION FROM RE.1 TO RS.10` -> 10.0. The same arithmetic,
    and the direction of the face value is what names the action."""
    parsed = p.parse("CONSOLIDATION FROM RE.1 TO RS.10")
    assert parsed.action_type == p.CONSOLIDATION
    assert parsed.price_factor == Decimal("10")


def test_a_split_is_typed_split_not_consolidation():
    assert p.parse("FACE VALUE SPLIT FROM RS.10 TO RS.2").action_type == p.SPLIT


def test_a_split_to_the_same_face_value_is_not_an_adjustment():
    """No change in face value is no change in the share count. Rejected rather
    than recorded as a 1.0 factor, because it means the string was misread."""
    parsed = p.parse("Face Value Split - From Rs 10/- Per Share To Rs 10/- Per Share")
    assert parsed.action_type == p.UNPARSED


# ─── Dividends: PRI leaves the price alone ──────────────────────────────────
# R10 and §5.3: `price_factor` is splits and bonuses only. Dividend-adjusting
# would make our 52-week highs disagree with every other quote site in India.


@pytest.mark.parametrize(
    ("purpose", "amount"),
    [
        ("DIVIDEND - RS 12 PER SHARE", Decimal("12")),  # the §5.3 example
        ("Dividend - Rs 0.005 Per Share", Decimal("0.005")),
        ("Interim Dividend - Rs  0.50 Per Share", Decimal("0.50")),
        ("Dividend - Re  0.50 Per Share", Decimal("0.50")),
        ("Interim Dividend - Re  1 Per Share", Decimal("1")),
        ("Dividend - Re 0.21 Per Sh", Decimal("0.21")),  # abbreviated
        ("Dividend - Rs1.25 Per Share", Decimal("1.25")),  # no space after Rs
        ("Special Dividend - Rs 4 Per Share", Decimal("4")),
    ],
)
def test_a_cash_dividend_leaves_the_price_factor_at_one(purpose, amount):
    parsed = p.parse(purpose)
    assert parsed.action_type == p.DIVIDEND
    assert parsed.price_factor == Decimal(1)
    assert parsed.dividend_per_share == amount


@pytest.mark.parametrize(
    ("purpose", "total"),
    [
        # 23 real strings carry two dividend clauses. They are one cash payment
        # in two parts, not a composite: both belong to the dividend family.
        ("Dividend - Rs 10 Per Share/Special Dividend - Rs 30 Per Share", Decimal("40")),
        ("Dividend - Re 1 Per Share/Special Dividend - Rs 2 Per Share", Decimal("3")),
        (
            "Dividend - Rs 2 Per Share & Special Dividend - Rs 1.60 Per Share",
            Decimal("3.60"),
        ),
        ("Dividend - Rs 20 Per Share/Special Dividend - Rs 7.50", Decimal("27.50")),
    ],
)
def test_two_dividend_clauses_are_summed(purpose, total):
    parsed = p.parse(purpose)
    assert parsed.action_type == p.DIVIDEND
    assert parsed.price_factor == Decimal(1)
    assert parsed.dividend_per_share == total


def test_a_trust_distribution_takes_its_headline_total():
    """InvIT and REIT payouts are one cash amount broken into interest,
    dividend and capital components. The headline is the total that goes ex,
    and the components are checked to sum to it."""
    purpose = (
        "Distribution - Rs 1.51 Consist Of Rs 1.06 Per Unit As Interest & "
        "Re 0.45 Per Unit As Repayment Of Capital"
    )
    parsed = p.parse(purpose)
    assert parsed.action_type == p.DIVIDEND
    assert parsed.price_factor == Decimal(1)
    assert parsed.dividend_per_share == Decimal("1.51")


def test_a_distribution_whose_parts_exceed_its_total_is_rejected():
    """A total cannot be smaller than its parts, so this falsifies "the
    headline is the total" and the amount is refused."""
    purpose = (
        "Distribution - Rs 1.00 Per Unit Consists Of Re 0.90 Per Unit As "
        "Interest & Re 0.90 Per Unit As Dividend"
    )
    assert p.parse(purpose).action_type == p.UNPARSED


def test_an_unrecognised_component_label_does_not_reject_the_distribution():
    """The other direction falsifies nothing. Component labels are open-ended —
    this real string carries "Repayment Of Shareholder Loan" and "Interest On
    Fixed Deposit" — and a two-sided check threw away six real strings it had
    in fact read correctly.
    """
    purpose = (
        "Distribution - Rs 5.25 Per Unit Consisting Of Interest - Rs 1.85 Per "
        "Unit/ Repayment Of Shareholder Loan - Rs 2.53 Per Unit/ Dividend - Re "
        "0.83 Per Unit/ Interest On Fixed Deposit - Re 0.04 Per Unit"
    )
    parsed = p.parse(purpose)
    assert parsed.action_type == p.DIVIDEND
    assert parsed.dividend_per_share == Decimal("5.25")


def test_a_cash_payment_with_no_stated_amount_still_leaves_the_price_alone():
    """"Interest Payment" carries no per-share figure. PRI is unaffected either
    way, so the factor is knowable even when the amount is not."""
    parsed = p.parse("Interest Payment")
    assert parsed.action_type == p.DIVIDEND
    assert parsed.price_factor == Decimal(1)
    assert parsed.dividend_per_share is None


# ─── tr_factor: the TRI half of the split ───────────────────────────────────


def test_tr_factor_of_the_section_5_3_worked_example():
    """₹12 on ₹840 -> 828/840 = 0.9857142857, against price_factor 1.0."""
    parsed = p.parse("DIVIDEND - RS 12 PER SHARE")
    assert p.tr_factor(parsed, prev_close=Decimal("840")) == Decimal("0.9857142857")


def test_tr_factor_equals_price_factor_when_there_is_no_dividend():
    """§5.3 defines tr_factor as price_factor x (prev - div)/prev, so with no
    dividend the two coincide — and it needs no previous close to say so."""
    parsed = p.parse("Bonus 1:1")
    assert p.tr_factor(parsed, prev_close=None) == Decimal("0.5")
    assert p.tr_factor(parsed, prev_close=Decimal("840")) == Decimal("0.5")


def test_tr_factor_is_unknown_until_a_previous_close_exists():
    """A dividend's TRI factor is a fraction of a price we do not have yet.
    None, never a guess: `daily_bars` is Phase 2."""
    parsed = p.parse("DIVIDEND - RS 12 PER SHARE")
    assert p.tr_factor(parsed, prev_close=None) is None


def test_tr_factor_combines_a_split_and_a_dividend():
    """0.2 x (840 - 12)/840 = 0.2 x 0.9857142857 = 0.1971428571."""
    parsed = p.ParsedAction(
        action_type=p.SPLIT,
        price_factor=Decimal("0.2"),
        dividend_per_share=Decimal("12"),
        ratio_text="10:2",
    )
    assert p.tr_factor(parsed, prev_close=Decimal("840")) == Decimal("0.1971428571")


def test_a_dividend_larger_than_the_price_is_rejected():
    """A payout exceeding the share price is impossible and would produce a
    negative factor. R5 — refuse rather than emit it."""
    parsed = p.parse("DIVIDEND - RS 900 PER SHARE")
    assert p.tr_factor(parsed, prev_close=Decimal("840")) is None


# ─── The non-equity trap ────────────────────────────────────────────────────


def test_a_bonus_of_preference_shares_is_not_an_equity_bonus():
    """The single most dangerous string in the real data.

    "Scheme Of Arrangement - Bonus Ncrps 46:1" is a bonus issue of
    non-convertible redeemable *preference* shares. Read as an equity bonus it
    gives 1/47 = 0.0213 — a 98% phantom crash applied to a stock that did not
    move. Three such strings appear in the 15-month window.
    """
    for purpose in (
        "Scheme Of Arrangement - Bonus Ncrps 46:1",
        "Scheme Of Arrangement - Bonus Ncrps 3:1",
        "Scheme Of Arrangement - Bonus Ncrps 4:1",
    ):
        parsed = p.parse(purpose)
        assert parsed.action_type == p.UNPARSED
        assert parsed.price_factor is None
        assert "NCRPS" in (parsed.reason or "").upper()


def test_a_rights_issue_of_warrants_is_not_an_equity_rights_issue():
    parsed = p.parse("Rights - 7 Ccps And 7 Warrants:40")
    assert parsed.action_type == p.UNPARSED
    assert parsed.price_factor is None


# ─── Rights and demerger: known action, unknowable factor ───────────────────


@pytest.mark.parametrize(
    "purpose",
    [
        "Rights 1:1 @ Premium Rs 0/-",
        "Rights 1:2 @ Premium Rs 290/-",
        "Rights 11:5 @ Premium Rs 54/-",
        "Rights 161:250 @ Premium Re 0.45 /-",
    ],
)
def test_a_rights_issue_is_typed_but_carries_no_factor(purpose):
    """The rights adjustment needs the cum price, which no purpose string
    contains. Typing it and leaving the factor absent is what makes §11.1
    suppress the window instead of applying a wrong number."""
    parsed = p.parse(purpose)
    assert parsed.action_type == p.RIGHTS
    assert parsed.price_factor is None
    assert parsed.ratio_text is not None


def test_a_demerger_is_typed_but_carries_no_factor():
    parsed = p.parse("Demerger")
    assert parsed.action_type == p.DEMERGER
    assert parsed.price_factor is None


def test_a_buyback_is_not_one_of_the_eight_action_types():
    """`Buy Back` has no row in the §5.3 enum and no ex-date price adjustment.
    Recorded as unparsed and suppressed rather than forced into a bucket."""
    assert p.parse("Buy Back").action_type == p.UNPARSED


# ─── Composite detection ────────────────────────────────────────────────────


def test_a_split_and_a_bonus_compose_in_execution_order():
    """§5.3: consolidation/split -> bonus -> rights -> dividend.
    0.2 x 0.5 = 0.1."""
    parsed = p.parse("SUB-DIVISION FROM RS 10 TO RS 2 AND BONUS IN 1:1 RATIO")
    assert parsed.action_type == p.COMPOSITE
    assert parsed.price_factor == Decimal("0.1")


def test_a_composite_whose_clause_fails_carries_no_factor():
    """§5.3 step 3: detected but unparseable -> COMPOSITE, NULL factor,
    UNPARSED, and suppress."""
    parsed = p.parse("SUB-DIVISION FROM RS 10 TO RS 2 AND BONUS IN SOME RATIO")
    assert parsed.action_type == p.COMPOSITE
    assert parsed.price_factor is None


def test_split_and_sub_division_are_one_action_not_two():
    """The false positive the real data is full of.

    Every one of the 53 face-value splits is titled "Face Value Split
    (Sub-Division)". Counting raw keywords makes each of them look like two
    actions, so all 53 would be suppressed as composites. SPLIT and
    SUB-DIVISION are one family.
    """
    parsed = p.parse(
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
    )
    assert parsed.action_type == p.SPLIT
    assert parsed.price_factor == Decimal("0.2")


def test_the_word_and_inside_one_clause_is_not_a_composite():
    """" AND " appears in six real strings, every one of them inside a single
    distribution breakdown. Splitting on it alone would misread all six."""
    purpose = (
        "Distribution - Rs 1.160 Per Unit Consists Of Re 1.157 Per Unit As "
        "Interest And Re 0.003 Per Unit As Other Income"
    )
    assert p.parse(purpose).action_type == p.DIVIDEND


def test_two_dividend_clauses_are_not_a_composite():
    parsed = p.parse("Dividend - Rs 10 Per Share/Special Dividend - Rs 30 Per Share")
    assert parsed.action_type == p.DIVIDEND


# ─── Refusal, never a guess ─────────────────────────────────────────────────


@pytest.mark.parametrize("purpose", ["", "   ", "Annual General Meeting", "???"])
def test_an_unrecognised_string_is_unparsed_with_a_reason(purpose):
    parsed = p.parse(purpose)
    assert parsed.action_type == p.UNPARSED
    assert parsed.price_factor is None
    assert parsed.reason


def test_a_bonus_with_a_zero_denominator_is_rejected():
    """0 held is not a ratio, and dividing by it would raise inside a loader."""
    assert p.parse("Bonus 1:0").action_type == p.UNPARSED


def test_a_split_from_a_zero_face_value_is_rejected():
    assert p.parse("Face Value Split - From Rs 0/- Per Share To Rs 2/- Per Share").action_type == (
        p.UNPARSED
    )


def test_every_result_is_one_of_the_eight_action_types():
    """The §5.3 CHECK constraint. A type the database refuses would abort the
    whole transaction on one bad string."""
    for row in fixtures():
        assert p.parse(row["purpose_raw"]).action_type in p.ACTION_TYPES


def test_parsing_is_deterministic():
    """R2's spirit: the parser is pure, so the same string is the same factor
    in the live path and in a replay."""
    for row in fixtures():
        assert p.parse(row["purpose_raw"]) == p.parse(row["purpose_raw"])


# ─── The acceptance criterion, over the real fixture ────────────────────────


def test_thirty_real_strings_are_typed_correctly():
    """BUILD_PLAN 1.3: >= 90% of a 30-string real fixture correctly typed."""
    rows = fixtures()
    assert len(rows) >= 30
    wrong = [
        (row["purpose_raw"], row["expected_action_type"], p.parse(row["purpose_raw"]).action_type)
        for row in rows
        if p.parse(row["purpose_raw"]).action_type != row["expected_action_type"]
    ]
    accuracy = 1 - len(wrong) / len(rows)
    assert accuracy >= 0.90, f"{accuracy:.0%} typed correctly; wrong: {wrong}"


def test_every_cash_dividend_in_the_fixture_has_price_factor_one():
    """BUILD_PLAN 1.3, stated separately because R10 makes it non-negotiable."""
    for row in fixtures():
        if row["expected_action_type"] != p.DIVIDEND:
            continue
        parsed = p.parse(row["purpose_raw"])
        assert parsed.price_factor == Decimal(1), row["purpose_raw"]


def test_no_fixture_string_produces_a_factor_without_a_reason_to():
    """Only splits, bonuses and consolidations move the price under PRI. Any
    other type carrying a factor other than 1.0 is a parser escaping its
    mandate."""
    for row in fixtures():
        parsed = p.parse(row["purpose_raw"])
        if parsed.action_type in (p.BONUS, p.SPLIT, p.CONSOLIDATION, p.COMPOSITE):
            continue
        assert parsed.price_factor in (None, Decimal(1)), row["purpose_raw"]


def test_every_unparsed_fixture_row_says_why():
    """"Every unparsed row is recorded, none silently dropped" starts here: a
    row cannot be recorded with a reason the parser did not give."""
    for row in fixtures():
        parsed = p.parse(row["purpose_raw"])
        if parsed.action_type == p.UNPARSED:
            assert parsed.reason, row["purpose_raw"]


def test_ratio_text_is_legible_not_exponential():
    """`ratio_text` exists to be read by a person checking a factor by hand.
    `Decimal("10").normalize()` is `1E+1`, which would render "1E+1:1"."""
    assert p.parse(
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share"
    ).ratio_text == "10:1"
    assert p.parse("Dividend - Rs 20 Per Share").ratio_text == "20 PER SHARE"
