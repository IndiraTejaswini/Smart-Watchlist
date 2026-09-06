"""Empirical CA factor verification — BUILD_PLAN task 1.4, ARCHITECTURE.md §5.3.

Written before the implementation, with every expectation computed by hand
(R11). §5.3 calls this the substitute for a second vendor feed: a parsed factor
makes a falsifiable prediction about the ex-date open, and the market either
confirms it or does not.

The arithmetic under test, verbatim from §5.3:

    prev     = close(symbol, previous_trading_day(ex_date))   # as-traded
    expected = prev * tr_factor
    observed = open_price(symbol, ex_date)
    observed_gap = observed / prev
    VERIFIED if abs(observed / expected - 1.0) <= CA_VERIFY_TOLERANCE else DISCREPANCY
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.constants import CA_VERIFY_TOLERANCE
from app.ingest import ca_verify as v
from app.ingest.bhavcopy import Bar

TOLERANCE = Decimal(str(CA_VERIFY_TOLERANCE))


# ─── The comparison ─────────────────────────────────────────────────────────


def test_a_perfect_match_verifies():
    """A 1:1 bonus on a ₹1000 close: expected 500, and the market opened there."""
    result = v.verify(
        tr_factor=Decimal("0.5"), prev_close=Decimal("1000"), ex_open=Decimal("500")
    )
    assert result.verification == v.VERIFIED
    assert result.deviation == Decimal("0")
    assert result.observed_gap == Decimal("0.5")


def test_a_small_deviation_still_verifies():
    """505 against an expected 500 is +1%, well inside the 8% tolerance. The
    band exists because a stock also moves on its own news that morning."""
    result = v.verify(
        tr_factor=Decimal("0.5"), prev_close=Decimal("1000"), ex_open=Decimal("505")
    )
    assert result.verification == v.VERIFIED
    assert result.deviation == Decimal("0.01")


def test_a_large_deviation_is_a_discrepancy():
    """560 against 500 is +12%, outside the band — the factor predicted a gap
    the market did not take."""
    result = v.verify(
        tr_factor=Decimal("0.5"), prev_close=Decimal("1000"), ex_open=Decimal("560")
    )
    assert result.verification == v.DISCREPANCY
    assert result.deviation == Decimal("0.12")


def test_the_tolerance_boundary_is_inclusive():
    """CA_VERIFY_TOLERANCE is 0.08, and §5.3 writes the test as `<=`. Exactly
    on the boundary verifies; a hair beyond it does not."""
    expected = Decimal("1000") * Decimal("0.5")
    on_boundary = expected * (Decimal(1) + TOLERANCE)
    assert (
        v.verify(
            tr_factor=Decimal("0.5"), prev_close=Decimal("1000"), ex_open=on_boundary
        ).verification
        == v.VERIFIED
    )
    assert (
        v.verify(
            tr_factor=Decimal("0.5"),
            prev_close=Decimal("1000"),
            ex_open=on_boundary + Decimal("0.01"),
        ).verification
        == v.DISCREPANCY
    )


def test_a_downward_deviation_is_measured_the_same_way():
    """The band is two-sided: a factor can over-predict the gap as easily as
    under-predict it."""
    result = v.verify(
        tr_factor=Decimal("0.5"), prev_close=Decimal("1000"), ex_open=Decimal("440")
    )
    assert result.verification == v.DISCREPANCY
    assert result.deviation == Decimal("-0.12")


def test_the_section_5_3_dividend_example_verifies():
    """₹12 on ₹840: tr_factor 0.9857142857, expected 828, and the market opened
    at 828."""
    result = v.verify(
        tr_factor=Decimal("0.9857142857"),
        prev_close=Decimal("840"),
        ex_open=Decimal("828"),
    )
    assert result.verification == v.VERIFIED


def test_the_observed_gap_is_against_the_previous_close_not_the_expectation():
    """§5.3 defines `observed_gap = observed / prev`. It is the raw fact the
    row records, so task 1.5 can snap it to a clean ratio later; the deviation
    is the separate quantity the verdict is made on."""
    result = v.verify(
        tr_factor=Decimal("0.5"), prev_close=Decimal("1000"), ex_open=Decimal("505")
    )
    assert result.observed_gap == Decimal("0.505")
    assert result.deviation == Decimal("0.01")


# ─── Refusal, never a verdict on absent data ────────────────────────────────


@pytest.mark.parametrize(
    ("tr_factor", "prev_close", "ex_open"),
    [
        (None, Decimal("1000"), Decimal("500")),
        (Decimal("0.5"), None, Decimal("500")),
        (Decimal("0.5"), Decimal("1000"), None),
    ],
)
def test_a_missing_input_leaves_the_row_unverified(tr_factor, prev_close, ex_open):
    """Absence of evidence is not a discrepancy. Marking one would suppress a
    symbol for the crime of having no bar on file — R5."""
    result = v.verify(tr_factor=tr_factor, prev_close=prev_close, ex_open=ex_open)
    assert result.verification == v.UNVERIFIED
    assert result.reason


@pytest.mark.parametrize(
    ("prev_close", "ex_open"),
    [
        (Decimal("0"), Decimal("500")),
        (Decimal("1000"), Decimal("0")),
        (Decimal("-1"), Decimal("5")),
    ],
)
def test_a_non_positive_price_is_not_verifiable(prev_close, ex_open):
    """A zero open is a symbol that did not trade, not a 100% crash."""
    result = v.verify(
        tr_factor=Decimal("0.5"), prev_close=prev_close, ex_open=ex_open
    )
    assert result.verification == v.UNVERIFIED


def test_a_zero_factor_is_not_verifiable():
    """Dividing by an expected price of zero would raise inside the job."""
    result = v.verify(
        tr_factor=Decimal("0"), prev_close=Decimal("1000"), ex_open=Decimal("500")
    )
    assert result.verification == v.UNVERIFIED


# ─── What the verdict means for suppression ─────────────────────────────────


def test_only_a_verified_row_is_safe_to_adjust_with():
    """§5.3's fail-safe rule: UNPARSED, COMPOSITE or DISCREPANCY suppress the
    window. UNVERIFIED is not yet evidence of anything, so it suppresses too —
    suppressing a real signal is a minor loss, showing a phantom crash is not.
    """
    assert v.is_trustworthy(v.VERIFIED)
    assert v.is_trustworthy(v.INFERRED)
    assert not v.is_trustworthy(v.DISCREPANCY)
    assert not v.is_trustworthy(v.UNVERIFIED)
    assert not v.is_trustworthy(v.UNPARSED)


# ─── The price source ───────────────────────────────────────────────────────


def _bar(symbol: str, day: date, open_: str, close: str, prev: str | None = None) -> Bar:
    return Bar(
        symbol=symbol,
        date=day,
        series="EQ",
        open=Decimal(open_),
        high=Decimal(open_),
        low=Decimal(open_),
        close=Decimal(close),
        prev_close=Decimal(prev) if prev else None,
        last=Decimal(close),
        volume=1,
        turnover=Decimal("1"),
        trades=1,
    )


class FakePrices:
    def __init__(self, bars):
        self._bars = {(b.symbol, b.date): b for b in bars}

    def bar(self, symbol, day):
        return self._bars.get((symbol, day))


def test_the_previous_close_comes_from_the_previous_trading_day():
    """§5.2: "the previous trading day" is not "yesterday". Reading the wrong
    session's close puts a verifiable factor a whole day out."""
    prices = FakePrices(
        [
            _bar("X", date(2026, 1, 23), "100", "100"),  # Friday
            _bar("X", date(2026, 1, 27), "50", "51"),  # Tuesday, ex-date
        ]
    )
    calendar = v.TradingCalendar.from_rows(
        [
            {"calendar_date": date(2026, 1, 23), "is_trading_day": True},
            {"calendar_date": date(2026, 1, 24), "is_trading_day": False},
            {"calendar_date": date(2026, 1, 25), "is_trading_day": False},
            {"calendar_date": date(2026, 1, 26), "is_trading_day": False},  # holiday
            {"calendar_date": date(2026, 1, 27), "is_trading_day": True},
        ]
    )
    pair = v.price_pair(prices, calendar, "X", date(2026, 1, 27))
    assert pair.prev_close == Decimal("100")
    assert pair.ex_open == Decimal("50")
    assert pair.prev_date == date(2026, 1, 23)


def test_an_ex_date_with_no_session_yields_no_prices():
    """A corporate action can carry an ex-date the exchange later moved. No bar
    means nothing to compare, not a discrepancy."""
    calendar = v.TradingCalendar.from_rows(
        [
            {"calendar_date": date(2026, 1, 23), "is_trading_day": True},
            {"calendar_date": date(2026, 1, 26), "is_trading_day": False},
        ]
    )
    pair = v.price_pair(FakePrices([]), calendar, "X", date(2026, 1, 26))
    assert pair.ex_open is None
    assert pair.reason


def test_the_exchanges_own_previous_close_is_cross_checked():
    """Measured on 6 September 2026: `PrvsClsgPric` on an ex-date is as-traded,
    at a ratio of exactly 1.0000 against the previous session's close on all
    eight samples. Were NSE to start pre-adjusting it, every verification would
    silently be comparing an adjusted price against an adjusted expectation and
    confirming itself, so the disagreement is surfaced rather than ignored.
    """
    prices = FakePrices(
        [
            _bar("X", date(2026, 1, 23), "100", "100"),
            _bar("X", date(2026, 1, 27), "50", "51", prev="50"),  # pre-adjusted
        ]
    )
    calendar = v.TradingCalendar.from_rows(
        [
            {"calendar_date": date(2026, 1, 23), "is_trading_day": True},
            {"calendar_date": date(2026, 1, 27), "is_trading_day": True},
        ]
    )
    pair = v.price_pair(prices, calendar, "X", date(2026, 1, 27))
    assert pair.prev_close == Decimal("100"), "the spec's source wins"
    assert pair.exchange_prev_close == Decimal("50")
    assert pair.prev_close_disagrees


def test_an_agreeing_exchange_previous_close_raises_no_flag():
    prices = FakePrices(
        [
            _bar("X", date(2026, 1, 23), "100", "100"),
            _bar("X", date(2026, 1, 27), "50", "51", prev="100"),
        ]
    )
    calendar = v.TradingCalendar.from_rows(
        [
            {"calendar_date": date(2026, 1, 23), "is_trading_day": True},
            {"calendar_date": date(2026, 1, 27), "is_trading_day": True},
        ]
    )
    assert not v.price_pair(prices, calendar, "X", date(2026, 1, 27)).prev_close_disagrees


# ─── Composite events: one ex-date, several rows ────────────────────────────


def _parsed(*purposes):
    from app.ingest import ca_parser

    return [ca_parser.parse(text) for text in purposes]


def test_two_actions_on_one_ex_date_compose_into_one_factor():
    """DELPHIFX 2026-02-13, from the real history: a 2:1 bonus and a 10->2
    split on the same date. 1/3 x 0.2 = 0.0666666667."""
    both = _parsed(
        "Bonus 2:1",
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share",
    )
    assert v.combined_tr_factor(both, prev_close=None) == Decimal("0.0666666667")


def test_composing_is_what_turns_a_false_discrepancy_into_a_verification():
    """The measurement that motivated this. DELPHIFX opened at 15.90 against a
    228.13 close. Its bonus alone predicts 76.04 — a -79% deviation, which reads
    as a catastrophic parser error. Composed with its split it predicts 15.21,
    which is +4.5% and verifies.
    """
    prev, ex_open = Decimal("228.13"), Decimal("15.90")
    bonus_only = v.verify(
        tr_factor=Decimal("0.3333333333"), prev_close=prev, ex_open=ex_open
    )
    assert bonus_only.verification == v.DISCREPANCY

    both = _parsed(
        "Bonus 2:1",
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share",
    )
    composed = v.verify(
        tr_factor=v.combined_tr_factor(both, prev), prev_close=prev, ex_open=ex_open
    )
    assert composed.verification == v.VERIFIED
    assert abs(composed.deviation) < Decimal("0.05")


def test_a_single_action_composes_to_itself():
    """One code path for both cases, so the common one cannot rot."""
    single = _parsed("Bonus 1:1")
    assert v.combine(single).price_factor == Decimal("0.5")
    assert v.combined_tr_factor(single, Decimal("1000")) == Decimal("0.5")


def test_a_split_and_a_dividend_on_one_date_combine_both_terms():
    """0.2 x (840 - 12)/840 = 0.1971428571."""
    both = _parsed("FACE VALUE SPLIT FROM RS.10 TO RS.2", "DIVIDEND - RS 12 PER SHARE")
    assert v.combined_tr_factor(both, Decimal("840")) == Decimal("0.1971428571")


def test_two_dividends_on_one_date_add_up():
    both = _parsed("Dividend - Rs 8 Per Share", "Special Dividend - Rs 4 Per Share")
    combined = v.combine(both)
    assert combined.price_factor == Decimal(1)
    assert combined.dividend_per_share == Decimal("12")


def test_one_unreadable_sibling_makes_the_whole_event_unverifiable():
    """R6. A rights issue states no factor, so the combined gap is unknowable
    and its sibling bonus cannot be tested against the open either."""
    combined = v.combine(_parsed("Bonus 1:1", "Rights 1:2 @ Premium Rs 290/-"))
    assert combined.price_factor is None
    assert combined.reason
    assert v.combined_tr_factor(_parsed("Bonus 1:1", "Demerger"), Decimal("100")) is None


def test_the_composed_factor_does_not_depend_on_the_order_of_the_rows():
    """The feed lists same-date actions in no guaranteed order."""
    forward = _parsed(
        "Bonus 2:1",
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share",
    )
    assert v.combine(forward).price_factor == v.combine(list(reversed(forward))).price_factor


def test_an_inferred_factor_is_not_re_verified_against_its_own_gap():
    """Regression, and the reason INFERRED is excluded from verification.

    Task 1.5 snaps a factor *from* the ex-date gap. Feeding that factor back
    into a test against the same gap confirms nothing — it verifies by
    construction — and it would overwrite the INFERRED verdict that §5.3
    requires be "flagged everywhere it appears", laundering a snapped guess into
    two independent sources agreeing.

    Found in a full-suite run: inference labelled eight rights and demerger rows
    INFERRED, and the next verification pass relabelled them VERIFIED.
    """
    inferred = v.ActionToVerify(
        id=1,
        symbol="X",
        ex_date=date(2026, 1, 27),
        action_type="RIGHTS",
        purpose_raw="Rights 3:4 @ Premium Rs 78/-",
        price_factor=Decimal("0.75"),
        verification=v.INFERRED,
    )
    parsed_row = v.ActionToVerify(
        id=2,
        symbol="Y",
        ex_date=date(2026, 1, 27),
        action_type="BONUS",
        purpose_raw="Bonus 1:1",
        price_factor=Decimal("0.5"),
        verification=v.UNVERIFIED,
    )
    prices = FakePrices(
        [
            _bar("X", date(2026, 1, 23), "100", "100"),
            _bar("X", date(2026, 1, 27), "75", "75"),
            _bar("Y", date(2026, 1, 23), "100", "100"),
            _bar("Y", date(2026, 1, 27), "50", "50"),
        ]
    )
    calendar = v.TradingCalendar.from_rows(
        [
            {"calendar_date": date(2026, 1, 23), "is_trading_day": True},
            {"calendar_date": date(2026, 1, 27), "is_trading_day": True},
        ]
    )
    report = v.VerifyReport(start=date(2026, 1, 23), end=date(2026, 1, 27))
    updates = v.verify_actions([inferred, parsed_row], prices, calendar, report)

    touched = {update["id"] for update in updates}
    assert 1 not in touched, "an inferred row must be left alone"
    assert 2 in touched, "a parsed row is still settled against the market"
