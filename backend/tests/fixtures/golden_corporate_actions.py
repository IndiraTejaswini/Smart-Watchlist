"""Verified NSE corporate-action examples used as adjustment goldens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CorporateActionFixture:
    symbol: str
    action_type: str
    cum_date: date
    ex_date: date
    as_traded_close: Decimal
    price_factor: Decimal
    expected_adjusted_close: Decimal
    volume_factor: Decimal
    source_url: str
    ratio: str | None = None
    dividend_amount: Decimal | None = None
    dividend_yield: Decimal | None = None


SOURCE_URL = "https://www.nseindia.com/companies-listing/corporate-filings-actions"

GOLDEN_CORPORATE_ACTIONS = (
    CorporateActionFixture(
        symbol="BPCL",
        action_type="BONUS",
        ratio="1:1",
        cum_date=date(2024, 6, 20),
        ex_date=date(2024, 6, 21),
        as_traded_close=Decimal("617.50"),
        price_factor=Decimal("0.500000"),
        expected_adjusted_close=Decimal("308.75"),
        volume_factor=Decimal("2.000000"),
        source_url=SOURCE_URL,
    ),
    CorporateActionFixture(
        symbol="NESTLEIND",
        action_type="SPLIT",
        ratio="10:1",
        cum_date=date(2024, 1, 4),
        ex_date=date(2024, 1, 5),
        as_traded_close=Decimal("27150.00"),
        price_factor=Decimal("0.100000"),
        expected_adjusted_close=Decimal("2715.00"),
        volume_factor=Decimal("10.000000"),
        source_url=SOURCE_URL,
    ),
    CorporateActionFixture(
        symbol="VEDL",
        action_type="SPECIAL_DIVIDEND",
        cum_date=date(2022, 5, 5),
        ex_date=date(2022, 5, 6),
        as_traded_close=Decimal("391.50"),
        price_factor=Decimal("0.9195402298850575"),
        expected_adjusted_close=Decimal("360.00"),
        volume_factor=Decimal("1.000000"),
        source_url=SOURCE_URL,
        dividend_amount=Decimal("31.50"),
        dividend_yield=Decimal("31.50") / Decimal("391.50"),
    ),
)
