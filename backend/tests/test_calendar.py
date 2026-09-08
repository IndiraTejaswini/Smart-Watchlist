"""Trading calendar acceptance — BUILD_PLAN task 1.2.

The three stated criteria are the last three tests in the pure section and are
repeated against the real loaded calendar in the database section:

  - `previous_trading_day` crosses a holiday correctly
  - a Muhurat day has `session_type='MUHURAT'`
  - `session_phase()` returns `PRE_OPEN` at 09:05 on a trading day

One deviation to note. The criterion says "a Muhurat **Saturday**". Muhurat
falls on a weekend most years but not on a Saturday in this window: NSE's
holiday master puts Diwali Laxmi Pujan on Sunday 08-Nov-2026, and the Muhurat
day inside the backfilled history is Tuesday 21-Oct-2025. Both are asserted —
the weekend one and the weekday one — since what the criterion is really
testing is that a Muhurat session is not classified by weekday.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.config import get_settings
from app.ingest import calendar as cal
from app.timeutil import (
    IST,
    NotATradingDayError,
    SessionPhase,
    SessionWindowUnknownError,
    previous_trading_day,
    session_close,
    session_phase,
    sessions_between,
)

# ─── Fixtures shaped like the real payloads ─────────────────────────────────

HOLIDAY_MASTER = json.dumps(
    {
        "CM": [
            {
                "tradingDate": "21-Oct-2025",
                "weekDay": "Tuesday",
                "description": "Diwali Laxmi Pujan",
                "Sr_no": 1,
            },
            {
                "tradingDate": "26-Jan-2026",
                "weekDay": "Monday",
                "description": "Republic Day",
                "Sr_no": 2,
            },
            {"tradingDate": "not-a-date", "description": "Malformed", "Sr_no": 3},
        ],
        "FO": [{"tradingDate": "26-Jan-2026", "description": "Republic Day"}],
    }
).encode()

# The footnote as NSE renders it, tags and all.
HOLIDAYS_PAGE = (
    b"<div class='col-md-12'><p>Note: <b>November 08, 2026,</b> shall be a "
    b"trading holiday on account of Diwali Laxmi Pujan. Muhurat Trading will be "
    b"conducted on that day. Timings of Muhurat Trading shall be notified "
    b"subsequently through a circular.</p><p>The holidays falling on Saturday / "
    b"Sunday are as follows:</p></div>"
)


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)


# ─── parse_holiday_master ───────────────────────────────────────────────────


def test_the_capital_market_segment_is_the_one_read():
    holidays = cal.parse_holiday_master(HOLIDAY_MASTER)
    assert {h.calendar_date for h in holidays} == {
        date(2025, 10, 21),
        date(2026, 1, 26),
    }


def test_an_unparsed_holiday_date_is_skipped_not_guessed():
    holidays = cal.parse_holiday_master(HOLIDAY_MASTER)
    assert all(isinstance(h.calendar_date, date) for h in holidays)


def test_a_missing_segment_yields_nothing_rather_than_raising():
    """NSE has restructured this payload before. An empty result is caught by
    the bhavcopy cross-check; an exception would take the whole load down."""
    assert cal.parse_holiday_master(b'{"FO": []}') == []


# ─── parse_muhurat_dates ────────────────────────────────────────────────────


def test_the_muhurat_date_is_read_from_the_footnote():
    """The holiday description is only "Diwali Laxmi Pujan*" — the asterisk is
    a marker, and the footnote is what it points at."""
    found = cal.parse_muhurat_dates(HOLIDAYS_PAGE)
    assert set(found) == {date(2026, 11, 8)}


def test_the_note_kept_is_what_the_exchange_actually_wrote():
    note = cal.parse_muhurat_dates(HOLIDAYS_PAGE)[date(2026, 11, 8)]
    assert "Muhurat Trading will be conducted" in note
    assert "notified subsequently" in note
    assert "<" not in note and ">" not in note


def test_a_page_with_no_muhurat_note_yields_nothing():
    assert cal.parse_muhurat_dates(b"<p>Note: markets are shut on Sunday.</p>") == {}


# ─── classify_day: the rules the two special sessions exercise ──────────────


def _classify(day: date, **kwargs):
    kwargs.setdefault("holidays", {})
    kwargs.setdefault("sessions_observed", {})
    kwargs.setdefault("muhurat_notes", {})
    return cal.classify_day(day, **kwargs)


def test_an_ordinary_weekday_is_a_regular_session_on_the_section_21_windows():
    day = date(2026, 9, 4)
    resolved = _classify(day, sessions_observed={day: True})
    assert resolved.is_trading_day
    assert resolved.session_type == cal.REGULAR
    assert resolved.pre_open_start == at(day, 9, 0)
    assert resolved.pre_open_end == at(day, 9, 15)
    assert resolved.regular_open == at(day, 9, 15)
    assert resolved.regular_close == at(day, 15, 30)


def test_no_post_close_window_is_invented():
    """§21 defines no post-close default, so the column stays NULL. R1."""
    day = date(2026, 9, 4)
    assert _classify(day, sessions_observed={day: True}).post_close_end is None


def test_a_listed_holiday_that_published_a_bhavcopy_is_a_muhurat_session():
    """2025-10-21. The two NSE sources disagree, and the observation wins: a
    published bhavcopy is the exchange saying a session happened."""
    day = date(2025, 10, 21)
    resolved = _classify(
        day, holidays={day: "Diwali Laxmi Pujan"}, sessions_observed={day: True}
    )
    assert resolved.session_type == cal.MUHURAT
    assert resolved.is_trading_day


def test_a_muhurat_session_borrows_no_window():
    """Inheriting 09:00-09:15 would report PRE_OPEN on a Diwali morning hours
    before the session opens — the §5.2 failure this table exists to prevent."""
    day = date(2025, 10, 21)
    resolved = _classify(
        day, holidays={day: "Diwali Laxmi Pujan"}, sessions_observed={day: True}
    )
    assert resolved.regular_open is None
    assert resolved.regular_close is None
    assert resolved.pre_open_start is None
    assert not resolved.has_known_window


def test_a_weekend_that_published_a_bhavcopy_is_a_full_session():
    """2026-02-01, the Budget Sunday. REGULAR describes the window, not the
    weekday: NSE announced no separate timings for it."""
    day = date(2026, 2, 1)
    resolved = _classify(day, sessions_observed={day: True})
    assert resolved.is_trading_day
    assert resolved.session_type == cal.REGULAR
    assert resolved.regular_open == at(day, 9, 15)
    assert "Special live session" in (resolved.notes or "")


def test_an_ordinary_weekend_is_closed():
    day = date(2026, 9, 5)
    resolved = _classify(day, sessions_observed={day: False})
    assert not resolved.is_trading_day
    assert resolved.session_type == cal.CLOSED


def test_a_listed_holiday_with_no_bhavcopy_is_closed_and_keeps_its_reason():
    day = date(2026, 1, 26)
    resolved = _classify(
        day, holidays={day: "Republic Day"}, sessions_observed={day: False}
    )
    assert not resolved.is_trading_day
    assert resolved.notes == "Republic Day"


def test_a_future_muhurat_date_is_a_trading_day_from_the_footnote_alone():
    """No bhavcopy can exist for a future date, so the footnote is the source."""
    day = date(2026, 11, 8)
    resolved = _classify(
        day, holidays={day: "Diwali Laxmi Pujan*"}, muhurat_notes={day: "Muhurat."}
    )
    assert resolved.is_trading_day
    assert resolved.session_type == cal.MUHURAT
    assert not resolved.has_known_window


def test_a_future_weekday_that_is_not_a_listed_holiday_is_a_trading_day():
    resolved = _classify(date(2026, 12, 1))
    assert resolved.is_trading_day and resolved.session_type == cal.REGULAR


def test_the_observed_record_outranks_the_holiday_list():
    """Both directions, since either source can be the wrong one."""
    day = date(2025, 10, 21)
    assert _classify(
        day, holidays={day: "Diwali"}, sessions_observed={day: True}
    ).is_trading_day
    assert not _classify(day, sessions_observed={day: False}).is_trading_day


# ─── build_calendar ─────────────────────────────────────────────────────────


def test_the_calendar_has_no_gaps():
    """A missing row inside the range would make `calendar.require()` fail on a
    date the range claims to cover — worse than a row saying the market shut."""
    start, end = date(2026, 1, 1), date(2026, 3, 31)
    days = cal.build_calendar(
        start, end, holidays={}, sessions_observed={}, muhurat_notes={}
    )
    assert len(days) == (end - start).days + 1
    assert [d.calendar_date for d in days] == [
        start + timedelta(days=i) for i in range((end - start).days + 1)
    ]


def test_an_inverted_window_is_an_error():
    with pytest.raises(cal.CalendarError):
        cal.build_calendar(
            date(2026, 3, 1),
            date(2026, 1, 1),
            holidays={},
            sessions_observed={},
            muhurat_notes={},
        )


def test_every_session_type_satisfies_the_check_constraint():
    days = cal.build_calendar(
        date(2025, 10, 20),
        date(2025, 10, 22),
        holidays={date(2025, 10, 21): "Diwali Laxmi Pujan"},
        sessions_observed={
            date(2025, 10, 20): True,
            date(2025, 10, 21): True,
            date(2025, 10, 22): False,
        },
        muhurat_notes={},
    )
    assert all(d.session_type in cal.SESSION_TYPES for d in days)


def test_cross_check_reports_a_holiday_that_traded():
    holidays = {date(2025, 10, 21): "Diwali Laxmi Pujan"}
    days = cal.build_calendar(
        date(2025, 10, 21),
        date(2025, 10, 21),
        holidays=holidays,
        sessions_observed={date(2025, 10, 21): True},
        muhurat_notes={},
    )
    lines = cal.cross_check(days, holidays)
    assert len(lines) == 1 and "MUHURAT" in lines[0]


# ─── inputs_digest ──────────────────────────────────────────────────────────


def test_the_digest_covers_the_window_as_well_as_the_files():
    """The same holiday files over a different range produce different rows, so
    a moved window is real work even when nothing was republished."""
    payloads = {"a.json": HOLIDAY_MASTER}
    a = cal.inputs_digest(payloads, (date(2026, 1, 1), date(2026, 3, 1)))
    b = cal.inputs_digest(payloads, (date(2026, 1, 1), date(2026, 4, 1)))
    assert a != b


def test_the_digest_is_order_independent():
    window = (date(2026, 1, 1), date(2026, 3, 1))
    assert cal.inputs_digest({"a": b"1", "b": b"2"}, window) == cal.inputs_digest(
        {"b": b"2", "a": b"1"}, window
    )


# ─── observed_sessions ──────────────────────────────────────────────────────


def test_weekdays_come_from_the_backfill_cache_with_no_network(tmp_path: Path):
    root = tmp_path / cal.BHAVCOPY_CACHE_DIR
    # Thursday the 3rd is the gap, and it sits inside the cached history rather
    # than past its end — beyond the end nothing is claimed at all.
    for day in ("2026-09-01", "2026-09-02", "2026-09-04"):
        (root / day).mkdir(parents=True)
        (root / day / "b.zip").write_bytes(b"x")
    observed = cal.observed_sessions(tmp_path, date(2026, 9, 1), date(2026, 9, 4), {})
    assert observed[date(2026, 9, 1)] is True
    assert observed[date(2026, 9, 3)] is False
    assert observed[date(2026, 9, 4)] is True


def test_an_empty_directory_is_not_a_session(tmp_path: Path):
    """A directory left behind by an interrupted download must not read as a
    trading day."""
    root = tmp_path / cal.BHAVCOPY_CACHE_DIR
    (root / "2026-09-01").mkdir(parents=True)
    (root / "2026-09-02").mkdir(parents=True)
    (root / "2026-09-02" / "b.zip").write_bytes(b"x")
    observed = cal.observed_sessions(tmp_path, date(2026, 9, 1), date(2026, 9, 2), {})
    assert observed[date(2026, 9, 1)] is False


def test_weekends_come_from_the_probe_ledger(tmp_path: Path):
    """The backfill only ever requested Mon-Fri, so a weekend session is
    invisible to the cache and has to be probed."""
    root = tmp_path / cal.BHAVCOPY_CACHE_DIR
    (root / "2026-01-30").mkdir(parents=True)
    (root / "2026-01-30" / "b.zip").write_bytes(b"x")
    (root / "2026-02-02").mkdir(parents=True)
    (root / "2026-02-02" / "b.zip").write_bytes(b"x")
    observed = cal.observed_sessions(
        tmp_path,
        date(2026, 1, 30),
        date(2026, 2, 2),
        {"2026-01-31": False, "2026-02-01": True},
    )
    assert observed[date(2026, 2, 1)] is True
    assert observed[date(2026, 1, 31)] is False


def test_nothing_is_claimed_beyond_the_cached_history(tmp_path: Path):
    """Dates after the last cached bhavcopy carry no observation at all, so a
    future date is resolved from the published sources rather than being
    recorded as a day that did not trade."""
    root = tmp_path / cal.BHAVCOPY_CACHE_DIR
    (root / "2026-09-04").mkdir(parents=True)
    (root / "2026-09-04" / "b.zip").write_bytes(b"x")
    observed = cal.observed_sessions(tmp_path, date(2026, 9, 4), date(2026, 12, 5), {})
    assert date(2026, 9, 4) in observed
    assert date(2026, 9, 7) not in observed


def test_the_history_window_starts_at_the_oldest_cached_bhavcopy(tmp_path: Path):
    root = tmp_path / cal.BHAVCOPY_CACHE_DIR
    for day in ("2025-09-11", "2026-09-04"):
        (root / day).mkdir(parents=True)
        (root / day / "b.zip").write_bytes(b"x")
    assert cal.earliest_cached_session(tmp_path) == date(2025, 9, 11)


def test_no_cached_bhavcopy_reads_as_absent(tmp_path: Path):
    assert cal.earliest_cached_session(tmp_path) is None


# ─── The three acceptance criteria, against a calendar built in memory ──────


def _built() -> list[cal.CalendarDay]:
    """The window around both Muhurat days and Republic Day 2026."""
    holidays = {
        date(2025, 10, 21): "Diwali Laxmi Pujan",
        date(2025, 10, 22): "Diwali Balipratipada",
        date(2026, 1, 26): "Republic Day",
        date(2026, 11, 8): "Diwali Laxmi Pujan*",
    }
    observed = {}
    day = date(2025, 10, 17)
    while day <= date(2026, 1, 30):
        observed[day] = day.weekday() < cal.SATURDAY and day not in holidays
        day += timedelta(days=1)
    observed[date(2025, 10, 21)] = True
    return cal.build_calendar(
        date(2025, 10, 17),
        date(2026, 11, 30),
        holidays=holidays,
        sessions_observed=observed,
        muhurat_notes={date(2026, 11, 8): "Muhurat Trading will be conducted."},
    )


def _calendar():
    return cal.TradingCalendar.from_rows(
        [
            {
                "calendar_date": d.calendar_date,
                "is_trading_day": d.is_trading_day,
                "session_type": d.session_type,
                "pre_open_start": d.pre_open_start,
                "pre_open_end": d.pre_open_end,
                "regular_open": d.regular_open,
                "regular_close": d.regular_close,
                "post_close_end": d.post_close_end,
            }
            for d in _built()
        ]
    )


def test_previous_trading_day_crosses_a_holiday():
    """Republic Day 2026 fell on a Monday, so the session before Tuesday the
    27th is Friday the 23rd — not "yesterday", which is the §5.2 point."""
    calendar = _calendar()
    assert previous_trading_day(date(2026, 1, 27), calendar) == date(2026, 1, 23)


def test_previous_trading_day_crosses_a_weekend_and_a_holiday_together():
    calendar = _calendar()
    assert previous_trading_day(date(2026, 1, 26), calendar) == date(2026, 1, 23)


def test_a_muhurat_weekend_day_has_session_type_muhurat():
    """The stated criterion. Muhurat is a Sunday in this window, not a
    Saturday — see the module docstring."""
    calendar = _calendar()
    session = calendar.sessions[date(2026, 11, 8)]
    assert session.session_type == "MUHURAT"
    assert session.is_trading_day
    assert date(2026, 11, 8).strftime("%A") == "Sunday"


def test_a_muhurat_weekday_is_also_muhurat():
    """Classification follows the exchange's sources, never the weekday."""
    calendar = _calendar()
    session = calendar.sessions[date(2025, 10, 21)]
    assert session.session_type == "MUHURAT"
    assert session.is_trading_day
    assert date(2025, 10, 21).strftime("%A") == "Tuesday"


def test_session_phase_is_pre_open_at_0905_on_a_trading_day():
    """The stated criterion. 09:05 sits inside the 09:00-09:15 pre-open, and
    §5.2 exists because treating it as open generates false gap alerts."""
    calendar = _calendar()
    day = date(2026, 1, 27)
    assert session_phase(at(day, 9, 5), calendar) is SessionPhase.PRE_OPEN
    assert session_phase(at(day, 9, 20), calendar) is SessionPhase.REGULAR
    assert session_phase(at(day, 8, 55), calendar) is SessionPhase.CLOSED
    assert session_phase(at(day, 15, 45), calendar) is SessionPhase.CLOSED


def test_a_muhurat_day_is_counted_but_refuses_to_state_a_phase():
    """It counts as a session, so SCAR's sqrt(n) is right; asking for its
    intraday phase raises rather than assuming regular hours."""
    calendar = _calendar()
    muhurat = date(2025, 10, 21)
    assert muhurat in calendar.trading_days
    with pytest.raises(SessionWindowUnknownError):
        session_phase(at(muhurat, 9, 5), calendar)
    with pytest.raises(SessionWindowUnknownError):
        session_close(muhurat, calendar)


def test_a_muhurat_day_still_counts_toward_the_session_count():
    calendar = _calendar()
    assert sessions_between(date(2025, 10, 20), date(2025, 10, 23), calendar) == 2


def test_a_closed_day_raises_a_different_error_than_an_unnotified_one():
    calendar = _calendar()
    with pytest.raises(NotATradingDayError):
        session_close(date(2026, 1, 26), calendar)


# ─── Against Postgres and the real loaded calendar ──────────────────────────


@pytest.fixture(scope="module")
def engine():
    engine = sa.create_engine(get_settings().database_url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001 — any connection failure is a skip
        pytest.skip(f"postgres unreachable ({type(exc).__name__}); run `make up`")
    return engine


@pytest.fixture(scope="module")
def cache_root():
    root = Path(get_settings().cache_root)
    if cal.earliest_cached_session(root) is None:
        pytest.skip("no cached bhavcopy; run `make backfill` first")
    return root


@pytest.fixture(scope="module")
def loaded(engine, cache_root):
    return cal.load(
        as_of=date.today(), from_cache_only=True, cache_root=cache_root, engine=engine
    )


def test_the_window_is_the_history_plus_ninety_days(loaded, cache_root):
    assert loaded.start == cal.earliest_cached_session(cache_root)
    assert loaded.end == date.today() + timedelta(days=cal.FORWARD_DAYS)


def test_every_date_in_the_window_has_exactly_one_row(loaded, engine):
    with engine.connect() as conn:
        count, lo, hi = conn.execute(
            sa.text(
                "SELECT COUNT(*), MIN(calendar_date), MAX(calendar_date) "
                "FROM trading_calendar"
            )
        ).one()
    assert lo == loaded.start and hi == loaded.end
    assert count == (hi - lo).days + 1


def test_a_regular_trading_day_carries_every_window_column(loaded, engine):
    """BUILD_PLAN 1.2 asks for the columns to be populated, not left to the
    reader's defaulting."""
    with engine.connect() as conn:
        missing = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM trading_calendar WHERE is_trading_day "
                "AND session_type = 'REGULAR' AND (pre_open_start IS NULL "
                "OR pre_open_end IS NULL OR regular_open IS NULL "
                "OR regular_close IS NULL)"
            )
        ).scalar_one()
    assert missing == 0


def test_no_non_trading_day_carries_a_window(loaded, engine):
    with engine.connect() as conn:
        bad = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM trading_calendar WHERE NOT is_trading_day "
                "AND (regular_open IS NOT NULL OR regular_close IS NOT NULL)"
            )
        ).scalar_one()
    assert bad == 0


def test_the_loaded_calendar_reads_back_into_a_trading_calendar(loaded, engine):
    """The load path and the read path have to agree, and a Muhurat row in the
    range must not stop the calendar being built at all."""
    with engine.connect() as conn:
        calendar = cal.load_trading_calendar(conn, loaded.start, loaded.end)
    assert calendar.start == loaded.start
    assert calendar.end == loaded.end
    assert len(calendar.trading_days) == loaded.trading_days


def test_the_real_muhurat_days_are_classified_muhurat(loaded, engine):
    with engine.connect() as conn:
        rows = dict(
            conn.execute(
                sa.text(
                    "SELECT calendar_date, is_trading_day FROM trading_calendar "
                    "WHERE session_type = 'MUHURAT'"
                )
            ).all()
        )
    assert date(2025, 10, 21) in rows, "Diwali Laxmi Pujan 2025, a listed holiday that traded"
    assert date(2026, 11, 8) in rows, "Diwali Laxmi Pujan 2026, named in the page footnote"
    assert all(rows.values()), "a Muhurat day is a trading day"


def test_the_budget_sunday_is_a_trading_day(loaded, engine):
    """The weekend session a weekday-only rule would have silently dropped."""
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT is_trading_day, session_type, regular_open FROM "
                "trading_calendar WHERE calendar_date = :d"
            ),
            {"d": date(2026, 2, 1)},
        ).one()
    assert row.is_trading_day
    assert row.session_type == "REGULAR"
    assert row.regular_open is not None


def test_every_cached_bhavcopy_date_is_a_trading_day(loaded, engine, cache_root):
    """The strongest consistency check available: a bar exists for every one of
    these dates, so a calendar calling any of them closed would make §6.1 skip
    a date it already has data for."""
    root = Path(cache_root) / cal.BHAVCOPY_CACHE_DIR
    cached = {
        date.fromisoformat(child.name)
        for child in root.iterdir()
        if child.is_dir() and any(child.glob("*.zip"))
    }
    with engine.connect() as conn:
        trading = {
            row[0]
            for row in conn.execute(
                sa.text("SELECT calendar_date FROM trading_calendar WHERE is_trading_day")
            )
        }
    assert cached - trading == set()


def test_no_trading_day_in_the_history_lacks_a_bhavcopy(loaded, engine, cache_root):
    """The converse. Any date here would be one §6.1 schedules an ingest for
    that will 404 every time."""
    root = Path(cache_root) / cal.BHAVCOPY_CACHE_DIR
    cached = {
        date.fromisoformat(child.name)
        for child in root.iterdir()
        if child.is_dir() and any(child.glob("*.zip"))
    }
    horizon = max(cached)
    with engine.connect() as conn:
        trading = {
            row[0]
            for row in conn.execute(
                sa.text(
                    "SELECT calendar_date FROM trading_calendar "
                    "WHERE is_trading_day AND calendar_date <= :h"
                ),
                {"h": horizon},
            )
        }
    assert trading - cached == set()


def test_previous_trading_day_crosses_a_real_holiday(loaded, engine):
    """Republic Day 2026 was a Monday, so Tuesday's previous session is the
    preceding Friday."""
    with engine.connect() as conn:
        calendar = cal.load_trading_calendar(conn, loaded.start, loaded.end)
    assert previous_trading_day(date(2026, 1, 27), calendar) == date(2026, 1, 23)


def test_session_phase_is_pre_open_at_0905_on_a_real_trading_day(loaded, engine):
    with engine.connect() as conn:
        calendar = cal.load_trading_calendar(conn, loaded.start, loaded.end)
    day = date(2026, 9, 4)
    assert session_phase(at(day, 9, 5), calendar) is SessionPhase.PRE_OPEN
    assert session_phase(at(day, 10, 0), calendar) is SessionPhase.REGULAR


def test_the_run_is_recorded_with_its_provenance(loaded, engine):
    """§6.2 rule 2 / R4. `trading_calendar` has no source column of its own, so
    the run row is where this load's provenance lives."""
    with engine.connect() as conn:
        status, rows, file_hash = conn.execute(
            sa.text(
                "SELECT status, rows, file_hash FROM ingest_runs WHERE source = :s "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"s": cal.SOURCE},
        ).one()
    assert status in ("OK", "SKIPPED_CACHED")
    assert rows == loaded.days
    assert file_hash == loaded.inputs_digest


def test_reloading_unchanged_inputs_changes_nothing(loaded, engine, cache_root):
    """§6.2 rules 1 and 3: idempotent, and a matching hash skips the work."""
    with engine.connect() as conn:
        before = conn.execute(
            sa.text(
                "SELECT COUNT(*), COUNT(*) FILTER (WHERE is_trading_day) "
                "FROM trading_calendar"
            )
        ).one()
    again = cal.load(
        as_of=date.today(), from_cache_only=True, cache_root=cache_root, engine=engine
    )
    with engine.connect() as conn:
        after = conn.execute(
            sa.text(
                "SELECT COUNT(*), COUNT(*) FILTER (WHERE is_trading_day) "
                "FROM trading_calendar"
            )
        ).one()
    assert before == after
    assert again.skipped_cached
    assert again.inputs_digest == loaded.inputs_digest


def test_the_only_source_disagreements_are_the_special_sessions(loaded):
    """Every disagreement between the observed record and the holiday list is
    accounted for. An unexplained one means a source went wrong."""
    assert len(loaded.disagreements) == len(
        [d for d in loaded.special_sessions if d.session_type == cal.MUHURAT]
    )
    assert all("MUHURAT" in line for line in loaded.disagreements)


def test_pending_windows_are_exactly_the_muhurat_days(loaded):
    """R1: the hours are not invented, so they are reported instead."""
    assert set(loaded.pending_windows) == {
        d.calendar_date for d in loaded.special_sessions if d.session_type == cal.MUHURAT
    }
