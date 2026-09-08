"""Trading calendar ingest — docs/BUILD_SPEC.md §5.2, BUILD_PLAN task 1.2.

Populates `trading_calendar` over the history window plus 90 days forward, as a
session state machine rather than a boolean. §5.2's reason: pre-open equilibrium
prices between 09:00 and 09:15 generate false gap alerts at open, and Muhurat
and half-day sessions break naive session-window logic. The sharper reason is
in `timeutil`: "the previous trading day" is not "yesterday", and a holiday
inside a window changes the session count, which changes the sqrt(n) in SCAR.

─── Sources, and how each was established ──────────────────────────────────

R3 forbids guessing market-data semantics, so every rule below is one the data
was checked against on 6 September 2026. `docs/data-notes.md` carries the
measurement; the short version:

  Holiday master   `/api/holiday-master?type=trading&year=YYYY`, segment `CM`.
                   The `year` parameter works, so history is reachable and not
                   only the current year. `CM` and `CBM` carry identical dates.

  Bhavcopy cache   Whether NSE published a bhavcopy for a date is the strongest
                   available evidence that a session happened, and it needs no
                   network: the Phase 0 backfill already cached 12 months. Over
                   that window the holiday master explains all 14 weekday gaps
                   with none unexplained, so the two sources agree completely
                   and each catches what the other cannot.

  Holidays page    The `*` footnote naming the Muhurat date. NSE states the
                   timings "shall be notified subsequently through a circular",
                   which is why `SessionWindowUnknownError` exists.

─── The two special sessions the naive rule would get wrong ────────────────

A weekday-and-not-a-holiday rule misses both of the exceptional days in the
window, in opposite directions:

  A listed holiday that traded anyway. 2025-10-21, Diwali Laxmi Pujan. NSE
  lists it as a trading holiday and published a bhavcopy for it, because a
  one-hour Muhurat session was held. Turnover was ₹19,552 Cr against ~₹110,000
  Cr on the surrounding days, and 9.0M trades against 34M — corroborating a
  short session, though the classification rests on the two NSE sources
  disagreeing, not on the turnover.

  A weekend that traded. 2026-02-01, a Sunday, full-size bhavcopy: the Union
  Budget special live session. Every one of the other 130 weekend dates in the
  window returns 404, and so do mock-trading Saturdays, so a published bhavcopy
  is a reliable signal of a real session rather than a rehearsal.

Muhurat hours are not resolvable from any reachable NSE source — see
`docs/data-notes.md`. Such a day is written as a trading day with a NULL
window, which `timeutil` holds as a first-class state, and is reported as
`pending_windows` on every run. R1: the hours are not invented.

    python -m app.ingest.calendar                      # fetch and load
    python -m app.ingest.calendar --from-cache-only
    python -m app.ingest.calendar --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.constants import CALENDAR_FORWARD_DAYS
from app.db import get_engine
from app.ingest import runs
from app.ingest.nse_client import (
    CacheMissError,
    NSEClient,
    NSEError,
    read_cached,
    sha256_bytes,
    write_cached,
)
from app.ingest.symbol_master import (
    CACHE_NAMESPACE,
    latest_cached_snapshot,
    snapshot_dir,
)
from app.timeutil import (
    CLOSE_TIME,
    IST,
    OPEN_TIME,
    PRE_OPEN_START_TIME,
    TradingCalendar,
)

log = logging.getLogger(__name__)

# ─── Sources ────────────────────────────────────────────────────────────────
# Addresses, not thresholds — the rule `backfill.py` and `symbol_master.py`
# both follow.

SOURCE = "trading_calendar"
NSE_HOME = "https://www.nseindia.com"
HOLIDAY_MASTER_URL = NSE_HOME + "/api/holiday-master?type=trading&year={year}"
HOLIDAYS_PAGE_URL = NSE_HOME + "/resources/exchange-communication-holidays"
HOLIDAYS_PAGE_REFERER = NSE_HOME + "/"

# The capital-market segment. `CBM` carries identical dates; measured, the two
# sets are equal, so one is read and the other ignored rather than merged.
CM_SEGMENT = "CM"

HOLIDAY_CACHE = "nse_holidays_{year}.json"
HOLIDAYS_PAGE_CACHE = "nse_holidays_page.html"
WEEKEND_PROBE_CACHE = "weekend_sessions.json"

# BUILD_PLAN 1.2, "plus 90 days forward" — R1: sourced from the registry.
FORWARD_DAYS = CALENDAR_FORWARD_DAYS

BHAVCOPY_CACHE_DIR = "bhavcopy"
BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
)

NSE_DATE_FORMAT = "%d-%b-%Y"

# ─── Session vocabulary — the §5.2 CHECK constraint ─────────────────────────

REGULAR = "REGULAR"
MUHURAT = "MUHURAT"
HALF_DAY = "HALF_DAY"
CLOSED = "CLOSED"
SESSION_TYPES = (REGULAR, MUHURAT, HALF_DAY, CLOSED)

SATURDAY = 5


class CalendarError(RuntimeError):
    """A calendar source could not be obtained or made sense of."""


# ─── Records ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Holiday:
    """One row of the NSE holiday master, for the capital-market segment."""

    calendar_date: date
    description: str


@dataclass(frozen=True)
class CalendarDay:
    """One `trading_calendar` row, fully resolved.

    A REGULAR trading day carries the §21 windows explicitly rather than
    leaving `timeutil` to default them: BUILD_PLAN 1.2 asks for the columns to
    be populated, and a materialised window is one that can be inspected in the
    database when a session boundary is ever in doubt.
    """

    calendar_date: date
    is_trading_day: bool
    session_type: str
    pre_open_start: datetime | None
    pre_open_end: datetime | None
    regular_open: datetime | None
    regular_close: datetime | None
    # §21 defines no post-close default, so it stays None until an exchange
    # source supplies one. R1: do not invent the number.
    post_close_end: datetime | None
    notes: str | None

    @property
    def has_known_window(self) -> bool:
        return self.regular_open is not None and self.regular_close is not None


@dataclass
class LoadReport:
    """What a run did, in the shape the acceptance criteria are stated in."""

    start: date
    end: date
    inputs_digest: str
    days: int = 0
    trading_days: int = 0
    session_type_counts: Counter[str] = field(default_factory=Counter)
    special_sessions: list[CalendarDay] = field(default_factory=list)
    pending_windows: list[date] = field(default_factory=list)
    disagreements: list[str] = field(default_factory=list)
    skipped_cached: bool = False

    def log(self) -> None:
        log.info(
            "trading calendar %s to %s: %d days, %d trading",
            self.start,
            self.end,
            self.days,
            self.trading_days,
        )
        for session_type in SESSION_TYPES:
            log.info(
                "  session_type %-9s %4d", session_type, self.session_type_counts[session_type]
            )
        for day in self.special_sessions:
            log.info(
                "  special session %s %s %s — %s",
                day.calendar_date,
                day.calendar_date.strftime("%A"),
                day.session_type,
                day.notes,
            )
        for pending in self.pending_windows:
            log.warning(
                "  %s is a trading day whose session window NSE has not "
                "published; session_phase() and session_close() will raise for "
                "it until a circular notifies the timings (§5.2, R1 — the hours "
                "are not invented)",
                pending,
            )
        for line in self.disagreements:
            log.warning("  source disagreement: %s", line)


# ─── Parsing — pure functions ───────────────────────────────────────────────


def parse_holiday_master(payload: bytes, *, segment: str = CM_SEGMENT) -> list[Holiday]:
    """The holiday master JSON -> the capital-market holidays it lists.

    A segment that is absent yields nothing rather than raising: NSE has
    restructured this payload before, and the bhavcopy cross-check below is what
    would catch a silent emptying over the history window.
    """
    document = json.loads(payload)
    rows = document.get(segment) or []
    holidays: list[Holiday] = []
    for row in rows:
        raw = str(row.get("tradingDate") or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.strptime(raw, NSE_DATE_FORMAT).date()
        except ValueError:
            log.warning("unparsed holiday date %r, skipped", raw)
            continue
        holidays.append(Holiday(parsed, str(row.get("description") or "").strip()))
    return holidays


# NSE's footnote, e.g. "November 08, 2026, shall be a trading holiday on
# account of Diwali Laxmi Pujan. Muhurat Trading will be conducted on that day."
# Anchored on "Muhurat" so an unrelated note about a different date cannot match.
_MUHURAT_NOTE = re.compile(
    r"([A-Z][a-z]+\s+\d{1,2},\s*\d{4})[^.]*?(?:trading holiday|holiday)[^.]*\."
    r"\s*Muhurat\s+Trading",
    re.IGNORECASE,
)
_MUHURAT_NOTE_DATE_FORMAT = "%B %d, %Y"


def parse_muhurat_dates(page_html: bytes) -> dict[date, str]:
    """{date: the sentence NSE wrote} for each Muhurat day the page names.

    Read from the footnote rather than inferred from the holiday description,
    because the description is only "Diwali Laxmi Pujan*" — the asterisk is the
    marker and the footnote is what it points at. Taking the sentence verbatim
    means the row's `notes` says what the exchange said, not a paraphrase.
    """
    text = re.sub(r"<[^>]+>", " ", page_html.decode("utf-8", errors="replace"))
    text = " ".join(text.split())
    found: dict[date, str] = {}
    for match in _MUHURAT_NOTE.finditer(text):
        raw = re.sub(r",\s*$", "", match.group(1).strip())
        try:
            parsed = datetime.strptime(raw, _MUHURAT_NOTE_DATE_FORMAT).date()
        except ValueError:
            log.warning("unparsed Muhurat note date %r, skipped", raw)
            continue
        sentence = " ".join(text[match.start() : match.start() + 400].split())
        sentence = sentence.split("The holidays falling")[0].strip()
        found[parsed] = sentence
    return found


def _at(day: date, hour_minute: Any) -> datetime:
    return datetime(
        day.year, day.month, day.day, hour_minute.hour, hour_minute.minute, tzinfo=IST
    )


def regular_day(day: date, *, notes: str | None = None) -> CalendarDay:
    """A full session on the §21 windows."""
    return CalendarDay(
        calendar_date=day,
        is_trading_day=True,
        session_type=REGULAR,
        pre_open_start=_at(day, PRE_OPEN_START_TIME),
        pre_open_end=_at(day, OPEN_TIME),
        regular_open=_at(day, OPEN_TIME),
        regular_close=_at(day, CLOSE_TIME),
        post_close_end=None,
        notes=notes,
    )


def closed_day(day: date, *, notes: str | None = None) -> CalendarDay:
    return CalendarDay(
        calendar_date=day,
        is_trading_day=False,
        session_type=CLOSED,
        pre_open_start=None,
        pre_open_end=None,
        regular_open=None,
        regular_close=None,
        post_close_end=None,
        notes=notes,
    )


def muhurat_day(day: date, *, notes: str | None = None) -> CalendarDay:
    """A Muhurat session: a trading day whose window NSE notifies separately.

    Every window stays None. Borrowing the §21 hours would report PRE_OPEN on a
    Diwali morning hours before the session opens, which is the exact failure
    §5.2 exists to prevent, and inventing the hour would break R1.
    """
    return CalendarDay(
        calendar_date=day,
        is_trading_day=True,
        session_type=MUHURAT,
        pre_open_start=None,
        pre_open_end=None,
        regular_open=None,
        regular_close=None,
        post_close_end=None,
        notes=notes,
    )


def classify_day(
    day: date,
    *,
    holidays: Mapping[date, str],
    sessions_observed: Mapping[date, bool],
    muhurat_notes: Mapping[date, str],
) -> CalendarDay:
    """Resolve one date into a calendar row.

    `sessions_observed` carries direct evidence — whether NSE published a
    bhavcopy — and is absent for future dates. Where it exists it wins, because
    a published bhavcopy is the exchange saying a session happened, and the
    holiday list is the exchange saying one was not scheduled. When those two
    disagree the observation is what actually occurred.
    """
    listed = holidays.get(day)
    observed = sessions_observed.get(day)
    weekend = day.weekday() >= SATURDAY

    if observed is True:
        if listed is not None:
            # A holiday that traded: a special session, and the only kind NSE
            # holds on a listed holiday is Muhurat.
            note = muhurat_notes.get(day) or (
                f"{listed}: listed as a trading holiday, but NSE published a "
                "bhavcopy for it — a Muhurat session was held. Timings are "
                "notified separately by circular and are not yet known."
            )
            return muhurat_day(day, notes=note)
        if weekend:
            # A weekend that traded on full hours — the Budget special live
            # session. REGULAR is a statement about the window, not the weekday.
            return regular_day(
                day,
                notes=(
                    "Special live session on a non-business day; NSE published a "
                    "full-size bhavcopy and announced no separate timings, so the "
                    "§21 regular windows apply."
                ),
            )
        return regular_day(day)

    if observed is False:
        if listed is not None:
            return closed_day(day, notes=listed)
        if weekend:
            return closed_day(day)
        # A weekday with no session and no listed holiday. Recorded as closed
        # because that is what was observed, and surfaced as a disagreement.
        return closed_day(day, notes="No bhavcopy published and no listed holiday.")

    # No observation: a future date, resolved from the published sources alone.
    if day in muhurat_notes:
        return muhurat_day(day, notes=muhurat_notes[day])
    if listed is not None:
        return closed_day(day, notes=listed)
    if weekend:
        return closed_day(day)
    return regular_day(day)


def build_calendar(
    start: date,
    end: date,
    *,
    holidays: Mapping[date, str],
    sessions_observed: Mapping[date, bool],
    muhurat_notes: Mapping[date, str],
) -> list[CalendarDay]:
    """Every date in [start, end], resolved. No gaps: a missing row inside the
    range would make `calendar.require()` fail on a date the range claims to
    cover, which is worse than a row saying the market was shut."""
    if end < start:
        raise CalendarError(f"end {end} precedes start {start}")
    days: list[CalendarDay] = []
    day = start
    while day <= end:
        days.append(
            classify_day(
                day,
                holidays=holidays,
                sessions_observed=sessions_observed,
                muhurat_notes=muhurat_notes,
            )
        )
        day += timedelta(days=1)
    return days


def cross_check(
    days: Sequence[CalendarDay], holidays: Mapping[date, str]
) -> list[str]:
    """Where the observed record and the published holiday list disagree.

    Reported rather than reconciled. Each disagreement is either a special
    session (expected, and already classified as one) or a sign that one of the
    two sources is wrong — and §6.2's whole posture is that a source being
    quietly wrong is the thing to surface.
    """
    lines: list[str] = []
    for day in days:
        listed = holidays.get(day.calendar_date)
        if day.is_trading_day and listed is not None:
            lines.append(
                f"{day.calendar_date} traded but is listed as a holiday ({listed}) "
                f"-> {day.session_type}"
            )
        elif (
            not day.is_trading_day
            and listed is None
            and day.calendar_date.weekday() < SATURDAY
            and day.notes
            and day.notes.startswith("No bhavcopy")
        ):
            lines.append(
                f"{day.calendar_date} is a weekday with no session and no listed "
                "holiday"
            )
    return lines


# ─── Fetching ───────────────────────────────────────────────────────────────


def observed_sessions(
    cache_root: Path, start: date, end: date, cached_weekends: Mapping[str, bool]
) -> dict[date, bool]:
    """Which dates in [start, end] NSE published a bhavcopy for.

    Weekdays come from the Phase 0 backfill cache with no network at all. The
    backfill only ever requested Mon-Fri, so weekends are unknown to it and are
    probed separately — which is how the Budget Sunday is found rather than
    assumed away.
    """
    bhavcopy_root = Path(cache_root) / BHAVCOPY_CACHE_DIR
    cached_days: set[date] = set()
    if bhavcopy_root.is_dir():
        for child in bhavcopy_root.iterdir():
            if not child.is_dir() or not any(child.glob("*.zip")):
                continue
            try:
                cached_days.add(date.fromisoformat(child.name))
            except ValueError:
                continue

    observed: dict[date, bool] = {}
    if not cached_days:
        return observed
    horizon = min(end, max(cached_days))
    day = start
    while day <= horizon:
        if day.weekday() < SATURDAY:
            observed[day] = day in cached_days
        elif day.isoformat() in cached_weekends:
            observed[day] = bool(cached_weekends[day.isoformat()])
        elif day in cached_days:
            observed[day] = True
        day += timedelta(days=1)
    return observed


def probe_weekend_sessions(
    client: NSEClient,
    *,
    start: date,
    end: date,
    as_of: date,
    cache_root: Path,
    from_cache_only: bool = False,
) -> dict[str, bool]:
    """Ask NSE whether each weekend date in the window published a bhavcopy.

    NSE serves 404 for a date it published nothing for, including mock-trading
    Saturdays, so a 200 means a real session. Results are cached as one JSON
    document per snapshot with a SHA-256 sidecar, the pattern `symbol_master`
    established for its vendor lookups: ~130 requests once, free thereafter.
    """
    cache_file = snapshot_dir(cache_root, as_of) / WEEKEND_PROBE_CACHE
    known: dict[str, bool] = {}
    cached = read_cached(cache_file)
    if cached is not None:
        known = {k: bool(v) for k, v in json.loads(cached).items()}

    wanted: list[date] = []
    day = start
    while day <= end:
        if day.weekday() >= SATURDAY and day.isoformat() not in known:
            wanted.append(day)
        day += timedelta(days=1)
    if not wanted:
        return known
    if from_cache_only:
        log.warning(
            "--from-cache-only: %d weekend dates were never probed; a special "
            "session on one of them would be recorded as closed",
            len(wanted),
        )
        return known

    log.info("probing %d weekend dates for a published bhavcopy", len(wanted))
    for probed, day in enumerate(wanted, start=1):
        try:
            payload = client.fetch(
                BHAVCOPY_URL.format(day=day),
                source=BHAVCOPY_CACHE_DIR,
                target_date=day,
                filename=f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip",
                endpoint="bhavcopy",
                accept_missing=True,
            )
        except NSEError as exc:
            log.warning("weekend probe for %s failed: %s", day, exc)
            continue
        known[day.isoformat()] = payload is not None
        if payload is not None:
            log.info("weekend session found: %s %s", day, day.strftime("%A"))
        if probed % 25 == 0:
            write_cached(cache_file, json.dumps(known, sort_keys=True).encode("utf-8"))
    write_cached(cache_file, json.dumps(known, sort_keys=True).encode("utf-8"))
    return known


def fetch_calendar_sources(
    client: NSEClient, *, as_of: date, years: Iterable[int]
) -> dict[str, bytes]:
    """The holiday master for each year in the window, plus the holidays page.

    A year the exchange has not published yet returns an empty segment rather
    than an error, so it is kept and reported as empty; the forward window can
    legitimately reach into a year whose holidays are not out.
    """
    payloads: dict[str, bytes] = {}
    for year in years:
        filename = HOLIDAY_CACHE.format(year=year)
        try:
            payload = client.fetch(
                HOLIDAY_MASTER_URL.format(year=year),
                source=CACHE_NAMESPACE,
                target_date=as_of,
                filename=filename,
                endpoint="holiday-master",
                referer=HOLIDAYS_PAGE_URL,
                accept_missing=True,
            )
        except (CacheMissError, NSEError) as exc:
            raise CalendarError(f"holiday master for {year} unavailable: {exc}") from exc
        if payload is None:
            raise CalendarError(f"holiday master for {year} is not published")
        payloads[filename] = payload

    try:
        page = client.fetch(
            HOLIDAYS_PAGE_URL,
            source=CACHE_NAMESPACE,
            target_date=as_of,
            filename=HOLIDAYS_PAGE_CACHE,
            endpoint="holidays-page",
            referer=HOLIDAYS_PAGE_REFERER,
            accept_missing=True,
        )
    except (CacheMissError, NSEError) as exc:
        log.warning("holidays page unavailable (%s); Muhurat dates unresolved", exc)
        page = None
    if page is not None:
        payloads[HOLIDAYS_PAGE_CACHE] = page
    return payloads


def inputs_digest(payloads: Mapping[str, bytes], window: tuple[date, date]) -> str:
    """One SHA-256 over every input, for §6.2 rule 3.

    The window is part of it: the same holiday files loaded over a different
    range produce different rows, so a run that moved the window has real work
    to do even when nothing was republished.
    """
    digest = hashlib.sha256()
    digest.update(f"{window[0].isoformat()}:{window[1].isoformat()}".encode("ascii"))
    for name in sorted(payloads):
        digest.update(name.encode("utf-8"))
        digest.update(sha256_bytes(payloads[name]).encode("ascii"))
    return digest.hexdigest()


# ─── Loading ────────────────────────────────────────────────────────────────

_UPSERT_DAY = sa.text(
    """
    INSERT INTO trading_calendar (
        calendar_date, is_trading_day, pre_open_start, pre_open_end,
        regular_open, regular_close, post_close_end, session_type, notes
    ) VALUES (
        :calendar_date, :is_trading_day, :pre_open_start, :pre_open_end,
        :regular_open, :regular_close, :post_close_end, :session_type, :notes
    )
    ON CONFLICT (calendar_date) DO UPDATE SET
        is_trading_day = EXCLUDED.is_trading_day,
        pre_open_start = EXCLUDED.pre_open_start,
        pre_open_end   = EXCLUDED.pre_open_end,
        regular_open   = EXCLUDED.regular_open,
        regular_close  = EXCLUDED.regular_close,
        post_close_end = EXCLUDED.post_close_end,
        session_type   = EXCLUDED.session_type,
        notes          = EXCLUDED.notes
    """
)


def load_trading_calendar(
    conn: sa.Connection, start: date, end: date
) -> TradingCalendar:
    """Read `trading_calendar` back into the frozen value the engine consumes.

    The counterpart to the write path, and the reason this module owns it: R2
    keeps the signal engine out of the database, so something on this side has
    to assemble the calendar and hand it down.
    """
    rows = conn.execute(
        sa.text(
            "SELECT calendar_date, is_trading_day, pre_open_start, pre_open_end, "
            "regular_open, regular_close, post_close_end, session_type "
            "FROM trading_calendar WHERE calendar_date BETWEEN :start AND :end "
            "ORDER BY calendar_date"
        ),
        {"start": start, "end": end},
    ).mappings()
    return TradingCalendar.from_rows([dict(row) for row in rows])


def load(
    *,
    as_of: date,
    forward_days: int = FORWARD_DAYS,
    from_cache_only: bool = False,
    cache_root: Path | None = None,
    dry_run: bool = False,
    engine: sa.Engine | None = None,
) -> LoadReport:
    """Fetch, resolve, and write the calendar. One transaction (§6.2 rule 7)."""
    from app.config import get_settings

    cache_root = Path(cache_root or get_settings().cache_root)
    snapshot = as_of
    if from_cache_only:
        found = latest_cached_snapshot(cache_root, as_of)
        if found is None:
            raise CalendarError(
                "--from-cache-only and no cached reference snapshot under "
                f"{cache_root / CACHE_NAMESPACE}"
            )
        snapshot = found
        log.info("reading the cached reference snapshot of %s", snapshot)

    start = earliest_cached_session(cache_root)
    if start is None:
        raise CalendarError(
            f"no cached bhavcopy under {cache_root / BHAVCOPY_CACHE_DIR}; run "
            "`make backfill` first — the history window is defined by what was "
            "downloaded"
        )
    end = as_of + timedelta(days=forward_days)
    years = range(start.year, end.year + 1)

    with NSEClient(from_cache_only=from_cache_only, cache_root=cache_root) as client:
        payloads = fetch_calendar_sources(client, as_of=snapshot, years=years)
        cached_weekends = probe_weekend_sessions(
            client,
            start=start,
            end=min(end, as_of),
            as_of=snapshot,
            cache_root=cache_root,
            from_cache_only=from_cache_only,
        )

    holidays: dict[date, str] = {}
    for year in years:
        for holiday in parse_holiday_master(payloads[HOLIDAY_CACHE.format(year=year)]):
            holidays[holiday.calendar_date] = holiday.description
    log.info("holiday master: %d capital-market holidays over %s", len(holidays), list(years))

    muhurat_notes: dict[date, str] = {}
    if HOLIDAYS_PAGE_CACHE in payloads:
        muhurat_notes = parse_muhurat_dates(payloads[HOLIDAYS_PAGE_CACHE])
        for day in sorted(muhurat_notes):
            log.info("holidays page names a Muhurat session on %s", day)

    sessions_seen = observed_sessions(cache_root, start, end, cached_weekends)
    days = build_calendar(
        start,
        end,
        holidays=holidays,
        sessions_observed=sessions_seen,
        muhurat_notes=muhurat_notes,
    )

    digest = inputs_digest(payloads, (start, end))
    report = LoadReport(start=start, end=end, inputs_digest=digest)
    report.days = len(days)
    report.trading_days = sum(1 for day in days if day.is_trading_day)
    report.session_type_counts = Counter(day.session_type for day in days)
    report.special_sessions = [
        day
        for day in days
        if day.is_trading_day
        and (day.session_type != REGULAR or day.calendar_date.weekday() >= SATURDAY)
    ]
    report.pending_windows = [
        day.calendar_date for day in days if day.is_trading_day and not day.has_known_window
    ]
    report.disagreements = cross_check(days, holidays)

    if dry_run:
        log.info("--dry-run: nothing written")
        report.log()
        return report

    engine = engine or get_engine()
    with engine.begin() as conn:
        if runs.already_ingested(conn, source=SOURCE, target_date=snapshot, file_hash=digest):
            log.info("calendar inputs unchanged since the last successful run (§6.2 rule 3)")
            runs.finish_run(
                conn,
                runs.start_run(conn, source=SOURCE, target_date=snapshot, file_hash=digest),
                status="SKIPPED_CACHED",
                rows=len(days),
            )
            report.skipped_cached = True
            report.log()
            return report

        run_id = runs.start_run(conn, source=SOURCE, target_date=snapshot, file_hash=digest)
        conn.execute(
            _UPSERT_DAY,
            [
                {
                    "calendar_date": day.calendar_date,
                    "is_trading_day": day.is_trading_day,
                    "pre_open_start": day.pre_open_start,
                    "pre_open_end": day.pre_open_end,
                    "regular_open": day.regular_open,
                    "regular_close": day.regular_close,
                    "post_close_end": day.post_close_end,
                    "session_type": day.session_type,
                    "notes": day.notes,
                }
                for day in days
            ],
        )
        runs.finish_run(conn, run_id, status="OK", rows=len(days))

    report.log()
    return report


def earliest_cached_session(cache_root: Path) -> date | None:
    """The start of the history window: the oldest bhavcopy the backfill cached.

    Defined by the data rather than by date arithmetic, so the calendar covers
    exactly the range the rest of the system has bars for and no further. A
    calendar claiming a range it cannot substantiate is what
    `CalendarRangeError` exists to prevent.
    """
    root = Path(cache_root) / BHAVCOPY_CACHE_DIR
    if not root.is_dir():
        return None
    days = []
    for child in root.iterdir():
        if not child.is_dir() or not any(child.glob("*.zip")):
            continue
        try:
            days.append(date.fromisoformat(child.name))
        except ValueError:
            continue
    return min(days) if days else None


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the trading calendar (§5.2).")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--forward-days", type=int, default=FORWARD_DAYS)
    parser.add_argument(
        "--from-cache-only",
        action="store_true",
        help="Never touch the network; read the newest cached snapshot.",
    )
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="Resolve and report without writing."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s"
    )
    try:
        load(
            as_of=args.as_of or datetime.now(tz=IST).date(),
            forward_days=args.forward_days,
            from_cache_only=args.from_cache_only,
            cache_root=args.cache_root,
            dry_run=args.dry_run,
        )
    except CalendarError as exc:
        log.error("trading calendar failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
