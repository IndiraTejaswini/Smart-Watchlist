"""Canonical corporate-action notices emitted by the scoring pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class CorporateActionNotice:
    """The audit-friendly payload shown when an ex-date is suppressed."""

    symbol: str
    ex_date: date
    cum_date: date
    action_type: str
    as_traded_cum_close: Decimal
    adjusted_prev_close: Decimal
    adjustment_factor: Decimal
    ratio_or_amount: str
    headline: str
    detail_text: str
    source_url: str
    created_at: datetime

