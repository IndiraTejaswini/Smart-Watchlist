"""IST and trading-calendar helpers — docs/BUILD_SPEC.md §4.3 and §5.2.

Two separate concerns live here, and the distinction matters:

  Timezone arithmetic. `ist_trading_date` needs nothing but the timestamp. IST
  is UTC+5:30 and India observes no daylight saving, so the conversion is
  total.

  Session arithmetic. Everything else is calendar-driven, never date
  arithmetic (§5.2). "The previous trading day" is not "yesterday", and a
  holiday inside a window changes the session count, which changes the sqrt(n)
  denominator in SCAR. Without a real calendar that is wrong and invisible.

Why the calendar is passed in rather than fetched. R2 makes the signal engine
a pure function: no database, no clock, no environment. A helper that looked
the calendar up itself could not be called from inside it. So `TradingCalendar`
is a frozen value assembled by the loader and handed down, and every helper
below is a pure function of its arguments. `sessions_between(a, b, calendar)`
returns the same answer in the live engine and in a replay of 2015.

The session-window defaults come from §21 (`SESSION_PRE_OPEN_START`,
`SESSION_OPEN`, `SESSION_CLOSE`) and an ingested calendar row overrides them
per date, which is what makes Muhurat and half-day sessions work.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from app.constants import (
    SESSION_CLOSE,
    SESSION_OPEN,
    SESSION_PRE_OPEN_START,
)

IST = ZoneInfo("Asia/Kolkata")


class SessionPhase(StrEnum):
    """§5.2. The phase a timestamp falls in, on its own IST date."""

    CLOSED = "CLOSED"
    PRE_OPEN = "PRE_OPEN"
    REGULAR = "REGULAR"
    POST_CLOSE = "POST_CLOSE"


class CalendarRangeError(LookupError):
    """A date was requested that the loaded calendar does not cover.

    Raised rather than answered with a guess: silently clamping to the nearest
    known date would return a plausible session count that is wrong, and
    nothing downstream could detect it.
    """


class NotATradingDayError(ValueError):
    """A session boundary was requested for a day that had no session."""


class SessionWindowUnknownError(ValueError):
    """A session happened, but the exchange has not published its window.

    The Muhurat case, and the reason this is a state rather than a rejection.
    NSE lists Diwali Laxmi Pujan as a trading holiday, conducts a one-hour
    Muhurat session on it anyway, and notifies the timings separately in a
    circular that can arrive weeks later — its own holiday page says so in
    as many words. So "a session occurred and we do not yet know its window"
    is a real, recurring state of the world, not a malformed row.

    It is raised here, when a window is actually needed, rather than when the
    calendar is built. Building is where `is_trading_day` matters, and
    `previous_trading_day` and `sessions_between` need nothing else — those two
    are the §5.2 reason this calendar exists, since a miscounted session
    changes the sqrt(n) in SCAR. Refusing to construct the calendar at all
    would take those down for every date over one unnotified hour on one day,
    and a Diwali falls inside every BETA_WINDOW_DAYS-length window once a year.

    Subclasses ValueError, so callers written against the earlier
    construction-time rejection still catch it.
    """


def _parse_hhmm(value: str) -> time:
    """Parse a "HH:MM" session default from §21."""
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


PRE_OPEN_START_TIME = _parse_hhmm(SESSION_PRE_OPEN_START)
OPEN_TIME = _parse_hhmm(SESSION_OPEN)
CLOSE_TIME = _parse_hhmm(SESSION_CLOSE)


@dataclass(frozen=True)
class Session:
    """One row of `trading_calendar` (§5.2).

    A REGULAR day fills any missing window from the §21 defaults. A MUHURAT or
    HALF_DAY day does not — it keeps its own hours, or carries none at all
    until the exchange notifies them. A non-trading day carries no windows.
    """

    calendar_date: date
    is_trading_day: bool
    session_type: str = "REGULAR"
    pre_open_start: datetime | None = None
    pre_open_end: datetime | None = None
    regular_open: datetime | None = None
    regular_close: datetime | None = None
    # No §21 default exists for the post-close window, so it stays None unless
    # the ingested calendar supplies it. R1: do not invent the number.
    post_close_end: datetime | None = None

    @property
    def has_known_window(self) -> bool:
        """Whether this session's open and close are known.

        False only for a trading day whose window the exchange has not yet
        published — see `SessionWindowUnknownError`. A scheduler checks this
        before timing a job off the session, rather than discovering the gap
        by catching an exception.
        """
        return self.regular_open is not None and self.regular_close is not None


def _at(d: date, t: time) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=IST)


def _session_from_row(row: Mapping[str, Any]) -> Session:
    """Build a Session, applying the §21 defaults only where they apply.

    The §21 defaults describe a REGULAR session. A MUHURAT or HALF_DAY session
    keeps its own hours and never borrows them: inheriting 09:00-09:15 would
    report PRE_OPEN on a Diwali morning hours before an evening session opens.
    §5.2 exists because naive session-window logic breaks on exactly these days.

    A non-regular row that states no hours therefore keeps none — the window
    stays None and any query needing it raises `SessionWindowUnknownError`,
    rather than the calendar refusing to exist. See that class for why the
    refusal moved from construction to the query: NSE routinely publishes the
    Muhurat date long before its timings, so this is a state the calendar has
    to be able to hold. No default is borrowed at any point, which is the rule
    this narrowing was written to enforce.
    """
    d = row["calendar_date"]
    trading = bool(row["is_trading_day"])
    session_type = row.get("session_type") or ("REGULAR" if trading else "CLOSED")

    if not trading:
        return Session(
            calendar_date=d, is_trading_day=False, session_type=session_type
        )

    if session_type == "REGULAR":
        return Session(
            calendar_date=d,
            is_trading_day=True,
            session_type=session_type,
            pre_open_start=row.get("pre_open_start") or _at(d, PRE_OPEN_START_TIME),
            pre_open_end=row.get("pre_open_end") or _at(d, OPEN_TIME),
            regular_open=row.get("regular_open") or _at(d, OPEN_TIME),
            regular_close=row.get("regular_close") or _at(d, CLOSE_TIME),
            post_close_end=row.get("post_close_end"),
        )

    return Session(
        calendar_date=d,
        is_trading_day=True,
        session_type=session_type,
        # Absent rather than defaulted: a session with no stated pre-open has
        # no PRE_OPEN phase, which is truthful. A wrong window is not.
        pre_open_start=row.get("pre_open_start"),
        pre_open_end=row.get("pre_open_end"),
        regular_open=row.get("regular_open"),
        regular_close=row.get("regular_close"),
        post_close_end=row.get("post_close_end"),
    )


@dataclass(frozen=True)
class TradingCalendar:
    """An immutable view of `trading_calendar` over a date range.

    Frozen and hashable because it is carried into the pure signal engine: a
    calendar a caller could mutate mid-computation would break the guarantee
    that `compute_signals(s, T, facts)` returns the same answer every time.
    """

    sessions: Mapping[date, Session]
    trading_days: tuple[date, ...]
    start: date
    end: date

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]]) -> TradingCalendar:
        sessions: dict[date, Session] = {}
        for row in rows:
            session = _session_from_row(row)
            if session.calendar_date in sessions:
                raise ValueError(
                    f"duplicate calendar row for {session.calendar_date}: the "
                    "calendar is keyed on calendar_date and cannot hold two."
                )
            sessions[session.calendar_date] = session
        if not sessions:
            raise ValueError("a trading calendar cannot be empty")
        ordered = sorted(sessions)
        return cls(
            sessions=MappingProxy(sessions),
            trading_days=tuple(d for d in ordered if sessions[d].is_trading_day),
            start=ordered[0],
            end=ordered[-1],
        )

    def __hash__(self) -> int:
        return hash((self.start, self.end, self.trading_days))

    def covers(self, d: date) -> bool:
        return self.start <= d <= self.end

    def require(self, d: date) -> Session:
        if not self.covers(d):
            raise CalendarRangeError(
                f"{d} is outside the loaded calendar ({self.start} to {self.end}). "
                "Extend the ingested range rather than assuming a session count."
            )
        return self.sessions[d]

    def is_trading_day(self, d: date) -> bool:
        return self.require(d).is_trading_day

    def is_holiday(self, d: date) -> bool:
        """Return whether the loaded calendar marks ``d`` as non-trading."""
        return not self.is_trading_day(d)

    def latest_completed_session(self, d: date) -> date:
        """Return the latest trading session on or before ``d``."""
        completed = [day for day in self.trading_days if day <= d]
        if not completed:
            raise CalendarRangeError(f"no completed trading session on or before {d}")
        return completed[-1]


class MappingProxy(Mapping):
    """A read-only, hashable-by-identity wrapper so `sessions` cannot be
    mutated through the frozen dataclass."""

    __slots__ = ("_data",)

    # Declared for the type checker only. `__slots__` creates the descriptor at
    # runtime and the annotation binds no class attribute, so this states the
    # element type without competing with the slot.
    _data: dict[date, Session]

    def __init__(self, data: dict[date, Session]) -> None:
        object.__setattr__(self, "_data", dict(data))

    def __getitem__(self, key: date) -> Session:
        return self._data[key]

    def __iter__(self) -> Iterator[date]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


# ─── timezone arithmetic ────────────────────────────────────────────────────


def ist_trading_date(ts: datetime) -> date:
    """The IST calendar date a timestamp falls on.

    The only way a trading date is ever derived (§4.3). Never `.date()` on a
    UTC timestamp: IST is UTC+5:30, so naive truncation puts a 19:00 IST
    announcement on the previous UTC day, and applies a corporate action's
    ex-date a day early or late — silently corrupting every price on the
    boundary.

    This returns the calendar date, not the next open session: 19:00 UTC on
    Friday is 00:30 IST on Saturday, and the answer is that Saturday. Rolling
    to a session is the calendar's job, not this function's.
    """
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError(
            "ist_trading_date requires an aware datetime. A naive timestamp has "
            "no defensible interpretation here, and guessing one is the most "
            "common silent bug in Indian market-data pipelines (§4.3)."
        )
    return ts.astimezone(IST).date()


# ─── calendar arithmetic ────────────────────────────────────────────────────


def session_phase(ts: datetime, calendar: TradingCalendar) -> SessionPhase:
    """Which phase of its own IST date a timestamp falls in.

    A boolean `is_trading_day` would be too thin (§5.2): pre-open equilibrium
    prices between 09:00 and 09:15 otherwise generate false gap alerts at open.

    POST_CLOSE is only reachable when the ingested calendar row carries
    `post_close_end`; §21 defines no default for it, so after the close a
    default-window day reads CLOSED.
    """
    d = ist_trading_date(ts)
    session = calendar.require(d)
    if not session.is_trading_day:
        return SessionPhase.CLOSED

    moment = ts.astimezone(IST)
    if not session.has_known_window:
        raise SessionWindowUnknownError(
            f"{d} is a trading day ({session.session_type}) whose session window "
            "the exchange has not published, so the phase at a given instant is "
            "not knowable. Assuming the §21 regular hours would report PRE_OPEN "
            "on a Diwali morning hours before the session opens."
        )
    assert session.regular_open is not None
    assert session.regular_close is not None

    # Each window is half-open, and anything falling in none of them is CLOSED.
    # Stated as membership rather than as an ordered ladder so that a day with
    # no pre-open, or a gap between pre-open and open, needs no special case.
    if (
        session.pre_open_start is not None
        and session.pre_open_end is not None
        and session.pre_open_start <= moment < session.pre_open_end
    ):
        return SessionPhase.PRE_OPEN
    if session.regular_open <= moment < session.regular_close:
        return SessionPhase.REGULAR
    if (
        session.post_close_end is not None
        and session.regular_close <= moment < session.post_close_end
    ):
        return SessionPhase.POST_CLOSE
    return SessionPhase.CLOSED


def previous_trading_day(d: date, calendar: TradingCalendar) -> date:
    """The last trading session strictly before `d`.

    Strictly before, so calling it on a trading day steps back a session rather
    than returning that day. "The previous trading day" is not "yesterday" —
    that is the whole reason this is calendar-driven (§5.2).
    """
    calendar.require(d)
    index = bisect.bisect_left(calendar.trading_days, d)
    if index == 0:
        raise CalendarRangeError(
            f"no trading day before {d} in the loaded calendar "
            f"(earliest is {calendar.start}). Extend the ingested range."
        )
    return calendar.trading_days[index - 1]


def session_close(d: date, calendar: TradingCalendar) -> datetime:
    """The close of `d`'s session, as an aware IST datetime.

    Anchors the §9.3 announcement linking window. A non-trading day has no
    close, and inventing one would link filings to a session that never
    happened, so it raises.

    The two absences are told apart, because they mean different things to a
    caller: a day that had no session at all, and a day that had one whose
    close the exchange has not yet published.
    """
    session = calendar.require(d)
    if not session.is_trading_day:
        raise NotATradingDayError(
            f"{d} is not a trading day ({session.session_type}), so it has no "
            "session close."
        )
    if session.regular_close is None:
        raise SessionWindowUnknownError(
            f"{d} is a trading day ({session.session_type}) whose close the "
            "exchange has not published. Filings cannot be linked to a session "
            "boundary that is not yet known."
        )
    return session.regular_close


def sessions_between(a: date, b: date, calendar: TradingCalendar) -> int:
    """Trading sessions in the half-open interval (a, b].

    Strictly after `a`, up to and including `b`. So `sessions_between(d, d)` is
    0, and one trading day to the next is 1.

    Why half-open. This is the n in the SCAR sqrt(n): a return accumulated from
    close(a) to close(b) spans exactly this many sessions, so the count and the
    number of returns being aggregated agree by construction. It also makes the
    function additive — n(a,c) == n(a,b) + n(b,c) — which is what lets the
    §13.4 recency decay computed in two hops agree with one computed directly.

    Endpoints need not themselves be trading days: a read cursor can sit at any
    instant. `b < a` returns a negative count.
    """
    if b < a:
        return -sessions_between(b, a, calendar)
    calendar.require(a)
    calendar.require(b)
    days = calendar.trading_days
    return bisect.bisect_right(days, b) - bisect.bisect_right(days, a)
