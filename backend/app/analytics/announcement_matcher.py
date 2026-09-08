"""Word-boundary announcement classification and candidate explainability."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.analytics.candidates import Candidate
from app.constants import ANNOUNCEMENT_TAIL_MINUTES
from app.ingest.announcement_ingest import Announcement
from app.timeutil import CLOSE_TIME, TradingCalendar, previous_trading_day

IST = ZoneInfo("Asia/Kolkata")


class AnnouncementCategory(StrEnum):
    FINANCIAL_RESULTS = "FINANCIAL_RESULTS"
    REGULATORY_ACTION = "REGULATORY_ACTION"
    MA_ACQUISITION = "MA_ACQUISITION"
    FUND_RAISE = "FUND_RAISE"
    ORDER_WIN = "ORDER_WIN"
    MANAGEMENT_CHANGE = "MANAGEMENT_CHANGE"
    GENERAL = "GENERAL"

    @property
    def priority(self) -> int:
        return list(type(self)).index(self) + 1


_PATTERNS: tuple[tuple[AnnouncementCategory, re.Pattern[str]], ...] = (
    (
        AnnouncementCategory.FINANCIAL_RESULTS,
        re.compile(
            r"\b(?:financial\s+results|audited\s+results|unaudited\s+results|"
            r"quarterly\s+results|q[1-4]\s+results|half\s+yearly\s+results|"
            r"annual\s+financial\s+results)\b",
            re.IGNORECASE,
        ),
    ),
    (
        AnnouncementCategory.REGULATORY_ACTION,
        re.compile(r"\b(?:regulatory|penalty|show\s+cause|investigation)\b", re.IGNORECASE),
    ),
    (
        AnnouncementCategory.MA_ACQUISITION,
        re.compile(r"\b(?:acquisition|merger|amalgamation|takeover)\b", re.IGNORECASE),
    ),
    (
        AnnouncementCategory.FUND_RAISE,
        re.compile(
            r"\b(?:fund\s+rais(?:ing|e)|preferential\s+allotment|qip|rights\s+issue|"
            r"qualified\s+institutions\s+placement|fpo)\b",
            re.IGNORECASE,
        ),
    ),
    (
        AnnouncementCategory.ORDER_WIN,
        re.compile(
            r"\b(?:order\s+win|bagged\s+(?:an\s+)?order|contract\s+awarded|"
            r"received\s+(?:a\s+)?contract|awarded\s+(?:a\s+)?project|purchase\s+order)\b",
            re.IGNORECASE,
        ),
    ),
    (
        AnnouncementCategory.MANAGEMENT_CHANGE,
        re.compile(
            r"\b(?:resignation|appointment|managing\s+director|chief\s+executive)\b",
            re.IGNORECASE,
        ),
    ),
)


def classify_announcement(
    headline: str, detail_text: str | None = None
) -> AnnouncementCategory:
    text = f"{headline} {detail_text or ''}"
    for category, pattern in _PATTERNS:
        if pattern.search(text):
            return category
    return AnnouncementCategory.GENERAL


def get_announcement_window(
    target_date: date, calendar: TradingCalendar
) -> tuple[datetime, datetime]:
    previous = previous_trading_day(target_date, calendar)
    window_end = datetime.combine(target_date, CLOSE_TIME, tzinfo=IST) + timedelta(
        minutes=ANNOUNCEMENT_TAIL_MINUTES
    )
    return (
        datetime.combine(previous, CLOSE_TIME, tzinfo=IST),
        window_end,
    )


def link_candidate_announcements(
    candidate: Candidate,
    announcements: list[Announcement],
    calendar: TradingCalendar,
) -> Candidate:
    start, end = get_announcement_window(candidate.date, calendar)
    matching = [
        announcement
        for announcement in announcements
        if announcement.symbol == candidate.symbol
        and start <= announcement.filed_at.astimezone(IST) <= end
    ]
    if not matching:
        return candidate
    categories = [
        classify_announcement(announcement.subject)
        for announcement in matching
    ]
    primary = min(categories, key=lambda category: category.priority)
    return replace(
        candidate,
        linked_announcement_ids=tuple(announcement.content_hash for announcement in matching),
        primary_category=primary.value,
        is_explained=True,
    )
