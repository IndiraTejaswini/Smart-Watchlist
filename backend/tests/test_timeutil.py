"""Tests for the IST and calendar helpers — ARCHITECTURE.md §4.3 and §5.2.

Written before the implementation. The two cases named in BUILD_PLAN task 0.6
are `test_acceptance_*` below.

Why this module gets its own test file: §4.3 calls naive UTC truncation "the
most common silent bug in Indian market-data pipelines", and §5.2 points out
that a holiday inside a window changes the session count, which changes the
sqrt(n) denominator in SCAR. Both failures are invisible in the output — the
numbers still look like numbers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.timeutil import (
    IST,
    CalendarRangeError,
    NotATradingDayError,
    SessionPhase,
    SessionWindowUnknownError,
    TradingCalendar,
    ist_trading_date,
    previous_trading_day,
    session_close,
    session_phase,
    sessions_between,
)


def build_calendar(
    start: date,
    end: date,
    holidays: set[date] | None = None,
    overrides: dict | None = None,
) -> TradingCalendar:
    """A weekday calendar over [start, end] with the given holidays removed.

    Real calendars are ingested in Phase 1.2; this is enough to exercise the
    helpers, and every test that cares about a holiday states it explicitly.
    """
    holidays = holidays or {}
    overrides = overrides or {}
    rows = []
    d = start
    while d <= end:
        trading = d.weekday() < 5 and d not in holidays
        rows.append(
            {
                "calendar_date": d,
                "is_trading_day": trading,
                "session_type": "REGULAR" if trading else "CLOSED",
                **overrides.get(d, {}),
            }
        )
        d += timedelta(days=1)
    return TradingCalendar.from_rows(rows)


# 2026-09-04 is a Friday; 09-05 Saturday, 09-06 Sunday, 09-07 Monday.
SEP = build_calendar(date(2026, 8, 1), date(2026, 10, 31))


# ─── the two acceptance cases from BUILD_PLAN 0.6 ───────────────────────────


def test_acceptance_1000z_is_the_same_ist_date():
    """10:00 UTC is 15:30 IST on the same day."""
    ts = datetime(2026, 9, 4, 10, 0, 0, tzinfo=UTC)
    assert ist_trading_date(ts) == date(2026, 9, 4)


def test_acceptance_1900z_rolls_to_the_next_ist_date():
    """19:00 UTC is 00:30 IST the following day.

    Note the expected answer is a Saturday: `ist_trading_date` returns the IST
    calendar date a timestamp falls on. It does not roll forward to the next
    open session — that is `previous_trading_day`'s and the calendar's job.
    """
    ts = datetime(2026, 9, 4, 19, 0, 0, tzinfo=UTC)
    assert ist_trading_date(ts) == date(2026, 9, 5)
    assert date(2026, 9, 5).weekday() == 5  # Saturday


# ─── ist_trading_date ───────────────────────────────────────────────────────


def test_naive_utc_truncation_would_be_wrong_and_we_do_not_do_it():
    """The §4.3 bug, stated as a test. A 19:00 IST filing is 13:30 UTC on the
    same day, so `.date()` on the UTC timestamp happens to agree here — but a
    23:00 IST filing is 17:30 UTC and a 00:30 IST filing is 19:00 UTC the day
    before. The second is where truncation silently loses a day."""
    ts = datetime(2026, 9, 4, 19, 0, 0, tzinfo=UTC)
    assert ts.date() == date(2026, 9, 4)  # what .date() would have said
    assert ist_trading_date(ts) == date(2026, 9, 5)  # what is actually true


def test_ist_midnight_boundary():
    """18:29:59 UTC is 23:59:59 IST; one second later is the next IST day."""
    assert ist_trading_date(datetime(2026, 9, 4, 18, 29, 59, tzinfo=UTC)) == date(
        2026, 9, 4
    )
    assert ist_trading_date(datetime(2026, 9, 4, 18, 30, 0, tzinfo=UTC)) == date(
        2026, 9, 5
    )


def test_ist_input_is_returned_unchanged():
    ts = datetime(2026, 9, 4, 19, 0, 0, tzinfo=IST)
    assert ist_trading_date(ts) == date(2026, 9, 4)


def test_other_zones_are_converted_not_truncated():
    ny = timezone(timedelta(hours=-4))
    # 2026-09-04 23:00 in UTC-4 is 2026-09-05 03:00 UTC, i.e. 08:30 IST.
    assert ist_trading_date(datetime(2026, 9, 4, 23, 0, tzinfo=ny)) == date(2026, 9, 5)


def test_naive_datetime_raises():
    """Guessing a zone is what produces the silent day-shift. Refuse."""
    with pytest.raises(ValueError):
        ist_trading_date(datetime(2026, 9, 4, 19, 0, 0))


# ─── session_phase ──────────────────────────────────────────────────────────
# Session defaults from §21: pre-open 09:00, open 09:15, close 15:30 IST.


def at(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST)


FRIDAY = date(2026, 9, 4)
SATURDAY = date(2026, 9, 5)
MONDAY = date(2026, 9, 7)


@pytest.mark.parametrize(
    "hh,mm,expected",
    [
        (8, 59, SessionPhase.CLOSED),
        (9, 0, SessionPhase.PRE_OPEN),
        (9, 14, SessionPhase.PRE_OPEN),
        (9, 15, SessionPhase.REGULAR),
        (12, 0, SessionPhase.REGULAR),
        (15, 29, SessionPhase.REGULAR),
        (15, 30, SessionPhase.CLOSED),
        (23, 0, SessionPhase.CLOSED),
    ],
)
def test_session_phase_across_a_regular_day(hh, mm, expected):
    assert session_phase(at(FRIDAY, hh, mm), SEP) is expected


def test_pre_open_is_not_regular():
    """§5.2: pre-open equilibrium prices between 09:00 and 09:15 otherwise
    generate false gap alerts at open."""
    assert session_phase(at(FRIDAY, 9, 5), SEP) is SessionPhase.PRE_OPEN
    assert session_phase(at(FRIDAY, 9, 5), SEP) is not SessionPhase.REGULAR


def test_non_trading_day_is_closed_all_day():
    for hh, mm in ((9, 0), (9, 15), (12, 0), (15, 29)):
        assert session_phase(at(SATURDAY, hh, mm), SEP) is SessionPhase.CLOSED


def test_holiday_is_closed_during_market_hours():
    cal = build_calendar(date(2026, 1, 1), date(2026, 2, 1), holidays={date(2026, 1, 26)})
    assert session_phase(at(date(2026, 1, 26), 12, 0), cal) is SessionPhase.CLOSED
    assert session_phase(at(date(2026, 1, 27), 12, 0), cal) is SessionPhase.REGULAR


def test_post_close_only_when_the_calendar_supplies_the_window():
    """§21 defines no post-close constant, so the helper must not invent one:
    with defaults alone, after 15:30 is CLOSED. When the ingested calendar row
    carries post_close_end, POST_CLOSE becomes reachable."""
    assert session_phase(at(FRIDAY, 15, 45), SEP) is SessionPhase.CLOSED

    cal = build_calendar(
        FRIDAY,
        FRIDAY,
        overrides={FRIDAY: {"post_close_end": at(FRIDAY, 16, 0)}},
    )
    assert session_phase(at(FRIDAY, 15, 45), cal) is SessionPhase.POST_CLOSE
    assert session_phase(at(FRIDAY, 16, 0), cal) is SessionPhase.CLOSED


def test_half_day_session_uses_the_calendar_window_not_the_default():
    """A HALF_DAY or MUHURAT session has its own hours. §5.2 exists precisely
    because naive session-window logic breaks on these."""
    muhurat = date(2026, 10, 20)
    cal = build_calendar(
        muhurat,
        muhurat,
        overrides={
            muhurat: {
                "is_trading_day": True,
                "session_type": "MUHURAT",
                "regular_open": at(muhurat, 18, 15),
                "regular_close": at(muhurat, 19, 15),
            }
        },
    )
    assert session_phase(at(muhurat, 12, 0), cal) is SessionPhase.CLOSED
    assert session_phase(at(muhurat, 18, 30), cal) is SessionPhase.REGULAR
    assert session_phase(at(muhurat, 19, 30), cal) is SessionPhase.CLOSED


def test_non_regular_session_does_not_inherit_the_regular_pre_open():
    """The §21 defaults describe a REGULAR day. Borrowing 09:00-09:15 for a
    Muhurat day would report PRE_OPEN on a Diwali morning, hours before an
    evening session opens."""
    muhurat = date(2026, 10, 20)
    cal = build_calendar(
        muhurat,
        muhurat,
        overrides={
            muhurat: {
                "is_trading_day": True,
                "session_type": "MUHURAT",
                "regular_open": at(muhurat, 18, 15),
                "regular_close": at(muhurat, 19, 15),
            }
        },
    )
    assert session_phase(at(muhurat, 9, 5), cal) is SessionPhase.CLOSED
    assert cal.sessions[muhurat].pre_open_start is None


def _unnotified(session_type: str, day: date) -> TradingCalendar:
    return TradingCalendar.from_rows(
        [{"calendar_date": day, "is_trading_day": True, "session_type": session_type}]
    )


def test_non_regular_session_without_hours_never_borrows_a_default():
    """An incomplete HALF_DAY row must not silently run on regular-day hours —
    R5, fail visibly. The window stays absent rather than being filled in."""
    half = date(2026, 9, 4)
    session = _unnotified("HALF_DAY", half).sessions[half]
    assert session.regular_open is None
    assert session.regular_close is None
    assert session.pre_open_start is None
    assert not session.has_known_window


def test_a_session_with_no_published_window_raises_where_the_window_is_needed():
    """Relocated from construction to the query — see SessionWindowUnknownError.

    NSE names the Muhurat date long before its timings, so the calendar has to
    be able to hold "a session happened, its window is not published yet".
    """
    half = date(2026, 9, 4)
    calendar = _unnotified("HALF_DAY", half)
    with pytest.raises(SessionWindowUnknownError, match="HALF_DAY"):
        session_phase(at(half, 11, 0), calendar)
    with pytest.raises(SessionWindowUnknownError, match="HALF_DAY"):
        session_close(half, calendar)


def test_an_unnotified_window_still_counts_as_a_session():
    """The whole reason the refusal moved: a miscounted session changes the
    sqrt(n) in SCAR, and a Diwali falls inside every 120-day window once a
    year. These two must keep working over an unnotified day."""
    muhurat = date(2026, 11, 9)
    calendar = TradingCalendar.from_rows(
        [
            {"calendar_date": date(2026, 11, 6), "is_trading_day": True},
            {"calendar_date": date(2026, 11, 7), "is_trading_day": False},
            {"calendar_date": date(2026, 11, 8), "is_trading_day": False},
            {
                "calendar_date": muhurat,
                "is_trading_day": True,
                "session_type": "MUHURAT",
            },
            {"calendar_date": date(2026, 11, 10), "is_trading_day": True},
        ]
    )
    assert muhurat in calendar.trading_days
    assert sessions_between(date(2026, 11, 6), date(2026, 11, 10), calendar) == 2
    assert previous_trading_day(date(2026, 11, 10), calendar) == muhurat


def test_a_non_trading_day_and_an_unnotified_window_are_different_failures():
    """A caller has to be able to tell "no session happened" from "a session
    happened and we do not know when"."""
    closed = date(2026, 11, 8)
    muhurat = date(2026, 11, 9)
    calendar = TradingCalendar.from_rows(
        [
            {"calendar_date": closed, "is_trading_day": False},
            {
                "calendar_date": muhurat,
                "is_trading_day": True,
                "session_type": "MUHURAT",
            },
        ]
    )
    with pytest.raises(NotATradingDayError):
        session_close(closed, calendar)
    with pytest.raises(SessionWindowUnknownError):
        session_close(muhurat, calendar)
    assert session_phase(at(closed, 11, 0), calendar) is SessionPhase.CLOSED


def test_regular_day_still_gets_the_section_21_defaults():
    """The narrowing above must not cost the common case its defaults."""
    session = SEP.sessions[FRIDAY]
    assert session.pre_open_start == at(FRIDAY, 9, 0)
    assert session.regular_open == at(FRIDAY, 9, 15)
    assert session.regular_close == at(FRIDAY, 15, 30)


def test_session_phase_accepts_utc_and_converts():
    """10:00 UTC is 15:30 IST — the close, so CLOSED, not REGULAR."""
    assert session_phase(datetime(2026, 9, 4, 10, 0, tzinfo=UTC), SEP) is (
        SessionPhase.CLOSED
    )
    assert session_phase(datetime(2026, 9, 4, 9, 59, tzinfo=UTC), SEP) is (
        SessionPhase.REGULAR
    )


def test_session_phase_outside_calendar_range_raises():
    with pytest.raises(CalendarRangeError):
        session_phase(at(date(2030, 1, 1), 12, 0), SEP)


def test_session_phase_rejects_naive():
    with pytest.raises(ValueError):
        session_phase(datetime(2026, 9, 4, 12, 0), SEP)


# ─── previous_trading_day ───────────────────────────────────────────────────


def test_previous_trading_day_is_strictly_before():
    assert previous_trading_day(MONDAY, SEP) == FRIDAY


def test_previous_trading_day_skips_the_weekend():
    assert previous_trading_day(SATURDAY, SEP) == FRIDAY
    assert previous_trading_day(date(2026, 9, 6), SEP) == FRIDAY


def test_previous_trading_day_is_not_yesterday():
    """§5.2: "the previous trading day" is not "yesterday"."""
    cal = build_calendar(
        date(2026, 1, 1), date(2026, 2, 1), holidays={date(2026, 1, 26)}
    )
    tuesday = date(2026, 1, 27)
    assert previous_trading_day(tuesday, cal) == date(2026, 1, 23)  # the Friday
    assert previous_trading_day(tuesday, cal) != tuesday - timedelta(days=1)


def test_previous_trading_day_from_a_trading_day_does_not_return_itself():
    assert previous_trading_day(FRIDAY, SEP) == date(2026, 9, 3)


def test_previous_trading_day_before_calendar_start_raises():
    """Falling off the start of the calendar must be loud. Silently returning
    the earliest known date would corrupt every window anchored on it."""
    cal = build_calendar(date(2026, 9, 1), date(2026, 9, 30))
    with pytest.raises(CalendarRangeError):
        previous_trading_day(date(2026, 9, 1), cal)


# ─── session_close ──────────────────────────────────────────────────────────


def test_session_close_is_1530_ist_by_default():
    close = session_close(FRIDAY, SEP)
    assert close == at(FRIDAY, 15, 30)
    assert close.utcoffset() == timedelta(hours=5, minutes=30)


def test_session_close_is_timezone_aware():
    assert session_close(FRIDAY, SEP).tzinfo is not None


def test_session_close_uses_a_calendar_override():
    half = date(2026, 9, 4)
    cal = build_calendar(
        half, half, overrides={half: {"regular_close": at(half, 13, 0)}}
    )
    assert session_close(half, cal) == at(half, 13, 0)


def test_session_close_of_a_non_trading_day_raises():
    """The §9.3 announcement linking window is anchored on a session close. A
    holiday has none, and inventing one would link filings to a session that
    never happened."""
    with pytest.raises(NotATradingDayError):
        session_close(SATURDAY, SEP)


# ─── sessions_between ───────────────────────────────────────────────────────
# Convention: trading sessions in the half-open interval (a, b] — strictly
# after a, up to and including b. This is the n in the SCAR sqrt(n): a return
# accumulated from close(a) to close(b) spans exactly that many sessions.


def test_sessions_between_same_day_is_zero():
    assert sessions_between(FRIDAY, FRIDAY, SEP) == 0


def test_sessions_between_consecutive_trading_days_is_one():
    assert sessions_between(date(2026, 9, 3), FRIDAY, SEP) == 1


def test_sessions_between_across_a_weekend_is_one():
    """Friday to Monday is one session, not three days. This is the whole
    point: calendar days and sessions are different units."""
    assert sessions_between(FRIDAY, MONDAY, SEP) == 1
    assert (MONDAY - FRIDAY).days == 3


def test_sessions_between_excludes_a_holiday():
    """§5.2: a holiday inside the window changes the session count, which
    changes the sqrt(n) denominator in SCAR."""
    cal = build_calendar(
        date(2026, 1, 1), date(2026, 2, 1), holidays={date(2026, 1, 26)}
    )
    # Fri 23 Jan -> Tue 27 Jan. Mon 26 is a holiday, so one session, not two.
    assert sessions_between(date(2026, 1, 23), date(2026, 1, 27), cal) == 1
    without_holiday = build_calendar(date(2026, 1, 1), date(2026, 2, 1))
    assert sessions_between(date(2026, 1, 23), date(2026, 1, 27), without_holiday) == 2


def test_sessions_between_a_full_week():
    assert sessions_between(date(2026, 8, 31), date(2026, 9, 4), SEP) == 4


def test_sessions_between_from_a_non_trading_start():
    """Counting from a Saturday is legitimate — a read cursor can sit at any
    instant — and the interval is open at the start, so the Saturday itself is
    never counted."""
    assert sessions_between(SATURDAY, MONDAY, SEP) == 1


def test_sessions_between_to_a_non_trading_end():
    """Closed at the end, but a Saturday is not a session, so it adds nothing."""
    assert sessions_between(FRIDAY, SATURDAY, SEP) == 0


def test_sessions_between_is_antisymmetric():
    assert sessions_between(MONDAY, FRIDAY, SEP) == -sessions_between(
        FRIDAY, MONDAY, SEP
    )


def test_sessions_between_is_additive_over_a_split_point():
    """n(a,c) == n(a,b) + n(b,c). Additivity is what lets a decay computed in
    two hops agree with one computed directly (§13.4)."""
    a, b, c = date(2026, 9, 1), date(2026, 9, 4), date(2026, 9, 10)
    assert sessions_between(a, c, SEP) == sessions_between(a, b, SEP) + (
        sessions_between(b, c, SEP)
    )


def test_sessions_between_outside_calendar_range_raises():
    with pytest.raises(CalendarRangeError):
        sessions_between(date(2020, 1, 1), FRIDAY, SEP)


# ─── the calendar container ─────────────────────────────────────────────────


def test_calendar_is_hashable_and_frozen():
    """The calendar is carried into the pure signal engine, so it must not be
    mutable state that a caller can change under it (R2)."""
    assert hash(SEP) == hash(SEP)
    with pytest.raises((AttributeError, TypeError)):
        SEP.sessions = {}


def test_trading_days_are_sorted_and_unique():
    days = SEP.trading_days
    assert list(days) == sorted(set(days))


def test_from_rows_rejects_duplicate_dates():
    with pytest.raises(ValueError):
        TradingCalendar.from_rows(
            [
                {"calendar_date": FRIDAY, "is_trading_day": True},
                {"calendar_date": FRIDAY, "is_trading_day": False},
            ]
        )


def test_helpers_never_call_the_clock():
    """R2: everything here is a pure function of its arguments and the
    calendar. A helper that reached for today() would make the replay engine
    disagree with the live engine."""
    import app.timeutil as tu

    source = tu.__file__
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    for forbidden in ("datetime.now(", "date.today(", "time.time("):
        assert forbidden not in text, f"{forbidden} found in timeutil.py"
