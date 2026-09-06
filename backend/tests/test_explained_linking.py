from dataclasses import replace
from datetime import date, datetime

from app.analytics.announcement_matcher import (
    AnnouncementCategory,
    classify_announcement,
    get_announcement_window,
    link_candidate_announcements,
)
from app.analytics.candidates import Candidate, SignalFamily
from app.ingest.announcement_ingest import Announcement
from app.timeutil import TradingCalendar


def _calendar() -> TradingCalendar:
    rows = [
        {"calendar_date": day, "is_trading_day": day not in {date(2026, 4, 6)}}
        for day in (date(2026, 4, 2), date(2026, 4, 3), date(2026, 4, 6), date(2026, 4, 7))
    ]
    return TradingCalendar.from_rows(rows)


def _candidate() -> Candidate:
    return Candidate(
        symbol="TATAMOTORS",
        date=date(2026, 4, 7),
        signal_families=frozenset({SignalFamily.PRICE_MPM}),
        primary_signal=SignalFamily.PRICE_MPM,
        sar=2.0,
        turnover_z=None,
        delivery_z=None,
        material_announcements_count=0,
    )


def _announcement(subject: str, filed_at: str, content_hash: str) -> Announcement:
    return Announcement(
        symbol="TATAMOTORS",
        filed_at=datetime.fromisoformat(filed_at),
        subject=subject,
        category="",
        para_ref=None,
        attachment_url=None,
        raw_json={},
        content_hash=content_hash,
    )


def test_post_close_filing_links_to_next_session_not_same_day() -> None:
    calendar = _calendar()
    announcement = _announcement(
        "Financial Results", "2026-04-06T19:00:00+05:30", "a1"
    )
    same_day = link_candidate_announcements(
        replace(_candidate(), date=date(2026, 4, 6)),
        [announcement],
        calendar,
    )
    next_day = link_candidate_announcements(_candidate(), [announcement], calendar)

    assert not same_day.is_explained
    assert next_day.is_explained
    start, end = get_announcement_window(date(2026, 4, 7), calendar)
    assert start.isoformat() == "2026-04-03T15:30:00+05:30"
    assert end.isoformat() == "2026-04-07T18:30:00+05:30"


def test_friday_evening_filing_crosses_holiday_to_tuesday() -> None:
    announcement = _announcement(
        "Financial Results", "2026-04-03T19:00:00+05:30", "a2"
    )
    linked = link_candidate_announcements(_candidate(), [announcement], _calendar())
    assert linked.linked_announcement_ids == ("a2",)


def test_word_boundaries_and_priority() -> None:
    assert (
        classify_announcement("Download the attachment for details")
        is AnnouncementCategory.GENERAL
    )
    assert (
        classify_announcement("Unconditional undertaking submitted")
        is AnnouncementCategory.GENERAL
    )
    assert (
        classify_announcement("Company bagged order worth Rs 500 Cr")
        is AnnouncementCategory.ORDER_WIN
    )
    assert (
        classify_announcement("Board approves fund raising via QIP")
        is AnnouncementCategory.FUND_RAISE
    )

    linked = link_candidate_announcements(
        _candidate(),
        [
            _announcement("General press release", "2026-04-07T16:00:00+05:30", "g"),
            _announcement("Audited quarterly financial results", "2026-04-07T16:05:00+05:30", "f"),
            _announcement("Bagged order for EV buses", "2026-04-07T16:10:00+05:30", "o"),
        ],
        _calendar(),
    )
    assert linked.is_explained
    assert len(linked.linked_announcement_ids) == 3
    assert linked.primary_category == AnnouncementCategory.FINANCIAL_RESULTS
