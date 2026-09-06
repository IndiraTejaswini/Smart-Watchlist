from datetime import date, timedelta

from app.analytics.candidates import Candidate, SignalFamily
from app.analytics.ranker import (
    PersonalContext,
    compute_personal_multiplier,
    rank_candidate,
)
from app.timeutil import TradingCalendar


def _calendar(start: date, end: date) -> TradingCalendar:
    rows = []
    current = start
    while current <= end:
        trading = current.weekday() < 5
        rows.append(
            {
                "calendar_date": current,
                "is_trading_day": trading,
                "session_type": "REGULAR" if trading else "CLOSED",
            }
        )
        current += timedelta(days=1)
    return TradingCalendar.from_rows(rows)


def _candidate(event_date: date) -> Candidate:
    return Candidate(
        symbol="TEST",
        date=event_date,
        signal_families=frozenset({SignalFamily.PRICE_MPM}),
        primary_signal=SignalFamily.PRICE_MPM,
        sar=2.5,
        turnover_z=2.0,
        delivery_z=2.0,
        material_announcements_count=1,
    )


def test_rank_candidate_matches_hand_computed_score() -> None:
    item = rank_candidate(
        _candidate(date(2026, 4, 6)),
        date(2026, 4, 8),
        PersonalContext(is_held=True),
        _calendar(date(2026, 4, 6), date(2026, 4, 8)),
    )
    assert item.recency_sessions == 2
    assert round(item.base_score, 4) == 2.0250
    assert round(item.decay_multiplier, 4) == 0.6703
    assert abs(item.final_score - 1.3574) < 1e-4


def test_personal_cap_clamps_all_triggers() -> None:
    raw, effective = compute_personal_multiplier(
        PersonalContext(
            is_held=True,
            is_pinned=True,
            is_recently_added=True,
            is_level_crossed=True,
        )
    )
    assert raw == 3.9
    assert effective == 2.0


def test_weekend_does_not_decay_friday_event_in_monday_brief() -> None:
    item = rank_candidate(
        _candidate(date(2026, 4, 10)),
        date(2026, 4, 13),
        PersonalContext(),
        _calendar(date(2026, 4, 10), date(2026, 4, 13)),
    )
    assert item.recency_sessions == 0
    assert item.decay_multiplier == 1.0
