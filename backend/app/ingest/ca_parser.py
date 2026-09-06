"""Corporate-action purpose parser — ARCHITECTURE.md §5.3, BUILD_PLAN task 1.3.

Turns a free-text NSE `subject` into an action type and a price factor. Pure:
no clock, no network, no database, so the same string is the same factor in the
live path and in a replay.

─── Why this file gets three defences and the announcement parser gets none ──

§5.3.0 rates this the only High-risk text parse in the system. Every number
that reaches the signal engine arrives as a typed column except this one, and a
wrong factor here renders a phantom crash that never happened — the worst
output this product can produce. So: parse (here), verify against the observed
ex-date gap (task 1.4), infer from the gap where the text failed (task 1.5), and
suppress on any doubt (§11.1).

This file is only the first of those, and its job is as much to *know when it
failed* as to succeed. Everything it cannot read becomes `UNPARSED` with a
stated reason rather than a plausible number.

─── PRI, not TRI ────────────────────────────────────────────────────────────

R10 and §5.3: `price_factor` covers splits, bonuses and consolidations only.
Cash dividends leave it at exactly 1.0 and populate `tr_factor`. Dividend-
adjusting the price series would make our 52-week highs and percentage changes
disagree with every other quote site in India, which a jury may well spot on a
familiar name.

─── What the real strings actually look like ────────────────────────────────

Measured over `/api/corporates-corporateActions` from 2025-09 to 2026-11:
2,121 rows, 594 distinct subjects. Three findings shape the code below, each
recorded in `docs/data-notes.md`:

  Splits are titled "Face Value Split (Sub-Division)". Counting action keywords
  makes every one of the 53 splits look like two actions, so a naive composite
  rule suppresses all of them. SPLIT and SUB-DIVISION are one family, and
  composite detection counts families, never keywords.

  " AND " never separates two action clauses. It appears in six strings, every
  one inside a single distribution breakdown ("...As Interest And ...As Other
  Income"). §5.3's " AND between two ratio clauses" rule is therefore applied
  only when the two sides belong to different families.

  Not every "Bonus n:m" is an equity bonus. "Scheme Of Arrangement - Bonus
  Ncrps 46:1" is a bonus of non-convertible redeemable *preference* shares.
  Read as equity it yields 1/47 — a 98% phantom crash. Non-equity instruments
  are refused outright.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from app.constants import CANONICAL_FLOAT_DP

# ─── The §5.3 action_type enum, mirrored from the CHECK constraint ──────────

BONUS = "BONUS"
SPLIT = "SPLIT"
CONSOLIDATION = "CONSOLIDATION"
DIVIDEND = "DIVIDEND"
RIGHTS = "RIGHTS"
DEMERGER = "DEMERGER"
COMPOSITE = "COMPOSITE"
UNPARSED = "UNPARSED"
ACTION_TYPES = (
    BONUS,
    SPLIT,
    CONSOLIDATION,
    DIVIDEND,
    RIGHTS,
    DEMERGER,
    COMPOSITE,
    UNPARSED,
)

# The types that move the price under PRI. Everything else is 1.0 or unknown.
PRICE_MOVING = (BONUS, SPLIT, CONSOLIDATION, COMPOSITE)

# NUMERIC(18,10) in the schema, and CANONICAL_FLOAT_DP is the §21 rounding the
# determinism contract already fixes at 8. Ten places is the column; quantising
# to it here means the value written is the value compared.
FACTOR_DP = Decimal(1).scaleb(-10)
_ = CANONICAL_FLOAT_DP  # the canonical layer rounds again on the way to a hash

# ─── Action families ────────────────────────────────────────────────────────
# Keyword -> family. Several keywords name one family, which is the whole point:
# "Face Value Split (Sub-Division)" names one action twice.

_FAMILY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("BONUS", BONUS),
    ("FACE VALUE SPLIT", SPLIT),
    ("SUB-DIVISION", SPLIT),
    ("SUBDIVISION", SPLIT),
    ("SUB DIVISION", SPLIT),
    ("STOCK SPLIT", SPLIT),
    ("SPLIT", SPLIT),
    ("CONSOLIDATION", CONSOLIDATION),
    ("CONSOLIDATE", CONSOLIDATION),
    ("REVERSE SPLIT", CONSOLIDATION),
    ("DIVIDEND", DIVIDEND),
    ("DISTRIBUTION", DIVIDEND),
    ("INTEREST PAYMENT", DIVIDEND),
    ("RIGHTS", RIGHTS),
    ("RIGHT ISSUE", RIGHTS),
    ("DEMERGER", DEMERGER),
)

# Instruments that are not the equity line. A bonus or rights issue of these
# changes no equity holder's share count, so an equity price factor derived
# from their ratio is pure fiction. Refused rather than approximated.
NON_EQUITY_INSTRUMENTS = (
    "NCRPS",
    "NCPS",
    "CCPS",
    "OCPS",
    "CCD",
    "NCD",
    "WARRANT",
    "PREFERENCE SHARE",
    "DEBENTURE",
)

# Components of a trust distribution. Used to check the parts against the
# headline total, never to pick the amount.
_DISTRIBUTION_COMPONENT = re.compile(
    r"(?:RS|RE)\s*\.?\s*(\d+(?:\.\d+)?)\s*(?:PER\s+UNIT\s*)?"
    r"(?:AS|IN\s+THE\s+FORM\s+OF)\s",
)
# "Interest - Rs 0.623 Per Unit" — the same components written the other way up.
# The label vocabulary is open-ended in the real data ("Repayment Of Shareholder
# Loan", "Interest On Fixed Deposit", ...), which is precisely why the check
# below is one-directional.
_DISTRIBUTION_COMPONENT_REVERSED = re.compile(
    r"(?:INTEREST(?:\s+ON\s+[A-Z ]+?)?|DIVIDEND|OTHER\s+INCOME|"
    r"RETURN\s+(?:OF|ON)\s+CAPITAL|REPAYMENT\s+OF\s+[A-Z ]+?|CAPITAL\s+REPAYMENT)"
    r"\s*[-:]?\s*(?:RS|RE)\s*\.?\s*(\d+(?:\.\d+)?)"
)
DISTRIBUTION_SUM_TOLERANCE = Decimal("0.02")

_RATIO = re.compile(r"(\d+)\s*:\s*(\d+)")
_FACE_VALUE_CHANGE = re.compile(
    r"FROM\s+(?:RS|RE)\s*\.?\s*(\d+(?:\.\d+)?)\s*(?:/-)?"
    r".*?TO\s+(?:RS|RE)\s*\.?\s*(\d+(?:\.\d+)?)",
    re.DOTALL,
)
# "Rs 12 Per Share", "Re 0.50 Per Sh", "Rs1.25 Per Share", "Rs 7.50" at the end
# of a clause. The per-share suffix is optional because NSE drops it in the
# second half of "Dividend - Rs 20 Per Share/Special Dividend - Rs 7.50".
_PER_SHARE_AMOUNT = re.compile(
    r"(?:RS|RE)\s*\.?\s*(\d+(?:\.\d+)?)\s*(?:/-)?(?:\s*PER\s+(?:SHARE|SH|UNIT)\b)?"
)
_HEADLINE_AMOUNT = re.compile(r"(?:RS|RE)\s*\.?\s*(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class ParsedAction:
    """The result of reading one `purpose_raw`.

    `price_factor` is the PRI factor: multiply an as-traded price before the
    ex-date by it to put it on the post-action basis. None means "this action
    moves the price and we could not say by how much", which §11.1 turns into a
    suppressed window — never into 1.0, which would claim no adjustment.
    """

    action_type: str
    price_factor: Decimal | None = None
    dividend_per_share: Decimal | None = None
    ratio_text: str | None = None
    reason: str | None = None


def _quantise(value: Fraction | Decimal) -> Decimal:
    """Land a factor on the NUMERIC(18,10) grid the column stores."""
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    return value.quantize(FACTOR_DP).normalize()


def _plain(value: Decimal) -> str:
    """A Decimal as a human reads it, never in exponent form.

    `Decimal("10").normalize()` is `1E+1`, which would put "1E+1:1" in
    `ratio_text` — a column whose only job is to be legible when someone is
    checking a factor by hand.
    """
    return format(value.normalize(), "f")


def normalise(purpose_raw: str) -> str:
    """Upper-case with collapsed whitespace — the form every rule below reads."""
    return " ".join(purpose_raw.upper().split())


def action_families(text: str) -> frozenset[str]:
    """The distinct action families a string names.

    Families, not keywords. "Face Value Split (Sub-Division)" names SPLIT twice
    and is one action; a string naming SPLIT and BONUS is two.
    """
    return frozenset(family for keyword, family in _FAMILY_KEYWORDS if keyword in text)


def non_equity_instrument(text: str) -> str | None:
    """The non-equity instrument this string is about, if any."""
    for instrument in NON_EQUITY_INSTRUMENTS:
        if instrument in text:
            return instrument
    return None


# ─── Per-family clause parsers ──────────────────────────────────────────────


def parse_bonus(text: str) -> ParsedAction:
    """"Bonus a:b" — a new shares for every b held, so factor = b / (a + b).

    §5.3 fixes the reading with two worked examples: 1:1 -> 0.5, 3:7 -> 0.7.
    """
    instrument = non_equity_instrument(text)
    if instrument is not None:
        return ParsedAction(
            UNPARSED,
            reason=(
                f"bonus issue of {instrument}, not equity — an equity factor from "
                "this ratio would adjust a price that never moved"
            ),
        )
    match = _RATIO.search(text)
    if match is None:
        return ParsedAction(UNPARSED, reason="bonus with no a:b ratio")
    new, held = int(match.group(1)), int(match.group(2))
    if new <= 0 or held <= 0:
        return ParsedAction(UNPARSED, reason=f"bonus ratio {new}:{held} is not a ratio")
    return ParsedAction(
        BONUS,
        price_factor=_quantise(Fraction(held, new + held)),
        ratio_text=f"{new}:{held}",
    )


def parse_face_value_change(text: str) -> ParsedAction:
    """A face-value split or consolidation — factor = to / from.

    The direction names the action: a smaller face value is a split (more
    shares, lower price), a larger one a consolidation.
    """
    match = _FACE_VALUE_CHANGE.search(text)
    if match is None:
        return ParsedAction(UNPARSED, reason="face-value change with no from/to values")
    try:
        old = Decimal(match.group(1))
        new = Decimal(match.group(2))
    except InvalidOperation:  # pragma: no cover - the regex only matches digits
        return ParsedAction(UNPARSED, reason="unreadable face values")
    if old <= 0 or new <= 0:
        return ParsedAction(UNPARSED, reason=f"face value {old} -> {new} is not positive")
    if old == new:
        return ParsedAction(
            UNPARSED,
            reason=f"face value unchanged at {old}; no share count changed",
        )
    return ParsedAction(
        SPLIT if new < old else CONSOLIDATION,
        price_factor=_quantise(new / old),
        ratio_text=f"{_plain(old)}:{_plain(new)}",
    )


def _distribution_total(text: str) -> tuple[Decimal | None, str | None]:
    """The headline amount of a trust distribution, checked against its parts.

    A distribution states its total first and then breaks it down, so the claim
    being tested is "the headline is the total". Summing the components is the
    parser's own evidence that it read the string correctly rather than picking
    up some other number in it.

    The test is one-directional, and the direction matters. Components summing
    to *more* than the headline falsifies the claim: a total cannot be smaller
    than its parts, so the headline is not the total and the amount is refused.
    Components summing to *less* falsifies nothing — it means a component label
    was not recognised, and the label vocabulary is open-ended in the real data.
    Measured over the 15-month window, all six strings that failed a two-sided
    check failed it that way, every one of them read correctly: the misses were
    "Repayment Of Shareholder Loan" and "Interest On Fixed Deposit".
    """
    headline = _HEADLINE_AMOUNT.search(text)
    if headline is None:
        return None, "distribution with no stated amount"
    total = Decimal(headline.group(1))
    components = [
        Decimal(value)
        for pattern in (_DISTRIBUTION_COMPONENT, _DISTRIBUTION_COMPONENT_REVERSED)
        for value in pattern.findall(text[headline.end() :])
    ]
    if components and sum(components) - total > DISTRIBUTION_SUM_TOLERANCE:
        return None, (
            f"distribution components sum to {sum(components)}, more than the "
            f"stated total of {total}, so the headline is not the total"
        )
    return total, None


def parse_dividend(text: str) -> ParsedAction:
    """A cash payout. `price_factor` is exactly 1.0 under PRI — R10, §5.3.

    The amount is summed across clauses: 23 real strings pay an ordinary and a
    special dividend on one ex-date ("Dividend - Rs 10 Per Share/Special
    Dividend - Rs 30 Per Share" is one ₹40 payment, not two actions).
    """
    if "DISTRIBUTION" in text:
        total, reason = _distribution_total(text)
        if total is None:
            return ParsedAction(UNPARSED, reason=reason)
        return ParsedAction(
            DIVIDEND, price_factor=Decimal(1), dividend_per_share=total,
            ratio_text=f"{_plain(total)} PER UNIT",
        )

    amounts = [Decimal(value) for value in _PER_SHARE_AMOUNT.findall(text)]
    if not amounts:
        # "Interest Payment" states no figure. PRI is unaffected either way, so
        # the factor is knowable even where the amount is not.
        return ParsedAction(DIVIDEND, price_factor=Decimal(1))
    total = sum(amounts, Decimal(0))
    return ParsedAction(
        DIVIDEND,
        price_factor=Decimal(1),
        dividend_per_share=total,
        ratio_text=f"{_plain(total)} PER SHARE",
    )


def parse_rights(text: str) -> ParsedAction:
    """A rights issue: typed, ratio kept, factor deliberately absent.

    The rights adjustment needs the cum price as well as the subscription
    price, and no purpose string carries the cum price. Leaving the factor None
    is what makes §11.1 suppress the window rather than apply a wrong number,
    and task 1.5 can still infer it from the observed gap.
    """
    instrument = non_equity_instrument(text)
    if instrument is not None:
        return ParsedAction(
            UNPARSED,
            reason=f"rights issue of {instrument}, not equity",
        )
    match = _RATIO.search(text)
    return ParsedAction(
        RIGHTS,
        ratio_text=f"{match.group(1)}:{match.group(2)}" if match else None,
        reason="rights factor needs the cum price, which the purpose string lacks",
    )


def parse_demerger(text: str) -> ParsedAction:
    """A demerger. The factor is the value split between the entities, which no
    purpose string states — real ones are the single word "Demerger"."""
    return ParsedAction(
        DEMERGER,
        reason="demerger factor is not stated in the purpose string",
    )


_FAMILY_PARSERS = {
    BONUS: parse_bonus,
    SPLIT: parse_face_value_change,
    CONSOLIDATION: parse_face_value_change,
    DIVIDEND: parse_dividend,
    RIGHTS: parse_rights,
    DEMERGER: parse_demerger,
}

# §5.3 step 2: exchange execution order.
COMPOSITION_ORDER = (CONSOLIDATION, SPLIT, BONUS, RIGHTS, DIVIDEND)


def _compose(text: str, families: frozenset[str]) -> ParsedAction:
    """Two or more families in one string — §5.3's composite case.

    Composed in execution order when every clause parses, and marked COMPOSITE
    with no factor when any clause does not. Rare by measurement: zero of the
    594 distinct real strings name two families. It exists because exchanges do
    publish them and the failure mode is severe.
    """
    factor = Decimal(1)
    dividend: Decimal | None = None
    parts: list[str] = []
    failed: list[str] = []

    for family in COMPOSITION_ORDER:
        if family not in families:
            continue
        parsed = _FAMILY_PARSERS[family](text)
        if parsed.action_type == UNPARSED or (
            family in PRICE_MOVING and parsed.price_factor is None
        ):
            failed.append(family)
            continue
        if parsed.price_factor is not None:
            factor *= parsed.price_factor
        if parsed.dividend_per_share is not None:
            dividend = (dividend or Decimal(0)) + parsed.dividend_per_share
        if parsed.ratio_text:
            parts.append(f"{family} {parsed.ratio_text}")

    if failed:
        return ParsedAction(
            COMPOSITE,
            ratio_text=" + ".join(parts) or None,
            reason=(
                "composite action whose "
                + ", ".join(sorted(failed))
                + " clause did not parse; suppressed under the §5.3 fail-safe rule"
            ),
        )
    return ParsedAction(
        COMPOSITE,
        price_factor=_quantise(factor),
        dividend_per_share=dividend,
        ratio_text=" + ".join(parts) or None,
    )


def parse(purpose_raw: str) -> ParsedAction:
    """Read one `purpose_raw` into an action type and, where knowable, a factor."""
    text = normalise(purpose_raw or "")
    if not text:
        return ParsedAction(UNPARSED, reason="empty purpose string")

    families = action_families(text)
    if not families:
        return ParsedAction(
            UNPARSED, reason="no recognised corporate-action keyword"
        )
    if len(families) > 1:
        return _compose(text, families)

    family = next(iter(families))
    return _FAMILY_PARSERS[family](text)


def tr_factor(parsed: ParsedAction, prev_close: Decimal | None) -> Decimal | None:
    """The §5.3 TRI factor: `price_factor x (prev - div) / prev`.

    Equals `price_factor` when there is no dividend, and the dividend gap when
    there is no split or bonus — which is what makes task 1.4 able to verify
    against it. Verifying against `price_factor` instead would mark every large
    special dividend a discrepancy, because the market gaps by the full
    economic adjustment while PRI deliberately holds the price factor at 1.0.

    None when the dividend's share of it cannot be computed: a previous close
    is a Phase 2 fact, and this returns nothing rather than a guess.
    """
    base = parsed.price_factor
    if base is None:
        return None
    dividend = parsed.dividend_per_share
    if dividend is None or dividend == 0:
        return _quantise(base)
    if prev_close is None or prev_close <= 0:
        return None
    if dividend >= prev_close:
        # A payout at or above the share price is impossible and would produce a
        # non-positive factor. R5: refuse rather than emit it.
        return None
    return _quantise(base * (prev_close - dividend) / prev_close)
