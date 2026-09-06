"""Immutable fact containers used by deterministic downstream evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class MarketModelFact:
    alpha: Decimal
    beta: Decimal
    r2: Decimal | None
    resid_sd: Decimal
    n_obs: int
    quality_flag: str


@dataclass(frozen=True)
class TurnoverBaselineFact:
    mean_log_turnover: Decimal
    std_log_turnover: Decimal
    n_obs: int
    quality_flag: str


@dataclass(frozen=True)
class DeliveryBaselineFact:
    raw_delivery_pct: Decimal
    logit_delivery: Decimal
    mean_logit_20d: Decimal
    std_logit_20d: Decimal
    delivery_z_score: Decimal
    n_obs: int
    quality_flag: str


@dataclass(frozen=True)
class ExtremesAdvFact:
    high_52w: Decimal
    low_52w: Decimal
    distance_to_52w_high_pct: Decimal
    distance_to_52w_low_pct: Decimal
    adv_20d: Decimal


@dataclass(frozen=True)
class AnnouncementFact:
    filed_at: datetime
    subject: str
    category: str
    attachment_url: str | None


@dataclass(frozen=True)
class DailyBarFact:
    adj_close: Decimal
    turnover: Decimal | None
    volume: int | None
    adj_prev_close: Decimal | None = None


@dataclass(frozen=True)
class Snapshot0930Fact:
    value: Decimal
    quality_flag: str


@dataclass(frozen=True)
class FactBundle:
    symbol: str
    date: date
    market_model: MarketModelFact | None = None
    turnover_baseline: TurnoverBaselineFact | None = None
    delivery_baseline: DeliveryBaselineFact | None = None
    extremes: ExtremesAdvFact | None = None
    recent_announcements: tuple[AnnouncementFact, ...] = ()
    current_bar: DailyBarFact | None = None
    index_snapshot_0930: Snapshot0930Fact | None = None
    completeness: frozenset[str] = frozenset()

    def is_complete(self, required: set[str]) -> bool:
        return required.issubset(self.completeness)
