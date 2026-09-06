"""Acceptance tests for refractory suppression and resets."""

from datetime import date, timedelta

from app.analytics.refractory import (
    CandidateEvent,
    RefractoryState,
    evaluate_refractory_filter,
)
from app.timeutil import TradingCalendar


def _calendar() -> TradingCalendar:
    start = date(2026, 4, 1)
    rows = [
        {
            "calendar_date": start + timedelta(days=index),
            "is_trading_day": True,
            "session_type": "REGULAR",
            "regular_open": "09:15",
            "regular_close": "15:30",
        }
        for index in range(10)
    ]
    return TradingCalendar.from_rows(rows)


def test_three_day_slide_and_escalation() -> None:
    calendar = _calendar()
    state = None
    emitted = 0
    for index, magnitude in enumerate((-0.04, -0.035, -0.042), 1):
        should_emit, state = evaluate_refractory_filter(
            CandidateEvent("AAA", date(2026, 4, index), magnitude), state, calendar
        )
        emitted += should_emit
    assert emitted == 1
    should_emit, state = evaluate_refractory_filter(
        CandidateEvent("AAA", date(2026, 4, 4), -0.065), state, calendar
    )
    assert should_emit
    assert state.anchor_magnitude == 0.065


def test_sign_flip_emits_immediately() -> None:
    calendar = _calendar()
    state = RefractoryState("AAA", date(2026, 4, 1), -1, 0.04)
    should_emit, state = evaluate_refractory_filter(
        CandidateEvent("AAA", date(2026, 4, 1), 0.04), state, calendar
    )
    assert should_emit
    assert state.direction == 1
