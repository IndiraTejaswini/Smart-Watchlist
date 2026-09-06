"""Validation of the verified corporate-action adjustment goldens."""

from __future__ import annotations

from decimal import Decimal

from tests.fixtures.golden_corporate_actions import GOLDEN_CORPORATE_ACTIONS


def test_all_golden_fixtures_load_cleanly() -> None:
    assert len(GOLDEN_CORPORATE_ACTIONS) == 3
    assert {fixture.symbol for fixture in GOLDEN_CORPORATE_ACTIONS} == {
        "BPCL",
        "NESTLEIND",
        "VEDL",
    }


def test_price_adjustments_match_expected_values() -> None:
    tolerance = Decimal("0.0000000000001")
    for fixture in GOLDEN_CORPORATE_ACTIONS:
        actual = fixture.as_traded_close * fixture.price_factor
        assert abs(actual - fixture.expected_adjusted_close) <= tolerance


def test_volume_factors_are_inverse_to_share_price_scaling() -> None:
    for fixture in GOLDEN_CORPORATE_ACTIONS:
        if fixture.action_type == "SPECIAL_DIVIDEND":
            assert fixture.volume_factor == Decimal("1.0")
        else:
            assert fixture.price_factor * fixture.volume_factor == Decimal("1.0")


def test_sources_are_explicit_nse_citations() -> None:
    for fixture in GOLDEN_CORPORATE_ACTIONS:
        assert fixture.source_url
        assert fixture.source_url.startswith("https://www.nseindia.com/")


def test_dividend_fixture_meets_extraordinary_yield_trigger() -> None:
    dividend = next(
        fixture
        for fixture in GOLDEN_CORPORATE_ACTIONS
        if fixture.action_type == "SPECIAL_DIVIDEND"
    )
    assert dividend.dividend_amount == Decimal("31.50")
    assert dividend.dividend_yield is not None
    assert dividend.dividend_yield >= Decimal("0.05")
