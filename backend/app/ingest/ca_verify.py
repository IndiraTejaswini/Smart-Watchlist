"""Empirical CA factor verification — docs/BUILD_SPEC.md §5.3, BUILD_PLAN task 1.4.

The morning job of §19.1, at 07:15, for yesterday's ex-dates — and the same
code run over the whole backfilled history, which is what makes the factors
already on disk trustworthy rather than merely parsed.

─── Why this exists ─────────────────────────────────────────────────────────

The review asked for a second vendor feed to cross-check parsed factors. No
free second source exists in the timebox, but §5.3 makes the sharper point:
**the market itself is a second source.** A parsed factor is a falsifiable
prediction about the ex-date open, and the exchange settles it every morning.

    prev     = close(symbol, previous_trading_day(ex_date))   # as-traded
    expected = prev * tr_factor
    observed = open_price(symbol, ex_date)
    observed_gap = observed / prev
    VERIFIED if abs(observed / expected - 1) <= CA_VERIFY_TOLERANCE else DISCREPANCY

The result is two independent estimators of one quantity — the text and the
price gap. Agreement is strong evidence; disagreement suppresses.

─── Against tr_factor, never price_factor ───────────────────────────────────

§5.3 is explicit, and it is the whole reason the PRI/TRI split is stored rather
than derived. The market gaps by the full economic adjustment, dividend
included; `price_factor` is deliberately 1.0 for a pure dividend under PRI, so
verifying against it would mark every large special dividend a discrepancy.
`tr_factor` equals `price_factor` when there is no dividend and equals the
dividend gap when there is no split, which makes it the one quantity the open
can be compared against in every case.

BUILD_PLAN 1.4 words this as "prev_adj_close x price_factor". Reconciled in
favour of §5.3, which states the rule twice and gives the reason; the build
plan's one-liner is the looser statement of the same job. Note also that no
adjustment of `prev` is needed: any cumulative factor before the ex-date
divides out of both sides of a ratio taken across a single session boundary.

─── Where the prices come from ──────────────────────────────────────────────

Through a `PriceSource`, because the answer changes by phase. `DailyBarsPrices`
reads `daily_bars` and is what runs once task 2.1 has filled it.
`CachedBhavcopyPrices` reads the Phase 0 backfill straight off disk, which is
what makes this task's acceptance — "running over the backfilled history" —
demonstrable before Phase 2 exists. The job logs which one it used; it never
falls back silently.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, DivisionByZero, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import sqlalchemy as sa

from app.constants import CA_VERIFY_TOLERANCE
from app.db import get_engine
from app.ingest import ca_parser
from app.ingest.bhavcopy import Bar, read_bhavcopy
from app.ingest.calendar import BHAVCOPY_CACHE_DIR, load_trading_calendar
from app.ingest.nse_client import read_cached
from app.timeutil import (
    IST,
    CalendarRangeError,
    TradingCalendar,
    previous_trading_day,
)

log = logging.getLogger(__name__)

SOURCE = "ca_verify"

# §5.3's verification enum.
VERIFIED = "VERIFIED"
INFERRED = "INFERRED"
DISCREPANCY = "DISCREPANCY"
UNVERIFIED = "UNVERIFIED"
UNPARSED = "UNPARSED"

# §5.3's fail-safe rule: UNPARSED, COMPOSITE or DISCREPANCY suppress the window.
# UNVERIFIED joins them because it is not yet evidence of anything — suppressing
# a real signal is a minor loss, rendering a phantom crash is catastrophic (R6).
TRUSTWORTHY = frozenset({VERIFIED, INFERRED})

TOLERANCE = Decimal(str(CA_VERIFY_TOLERANCE))
# The deviation is a ratio, reported for a human to read. Ten places is the
# NUMERIC(12,6) column with room to spare.
_DEVIATION_DP = Decimal("0.000001")


def is_trustworthy(verification: str) -> bool:
    """Whether a factor may be applied to a price series at all."""
    return verification in TRUSTWORTHY


@dataclass(frozen=True)
class Verification:
    """The verdict on one parsed factor, and the numbers behind it."""

    verification: str
    observed_gap: Decimal | None = None
    expected_gap: Decimal | None = None
    deviation: Decimal | None = None
    reason: str | None = None


def verify(
    *,
    tr_factor: Decimal | None,
    prev_close: Decimal | None,
    ex_open: Decimal | None,
) -> Verification:
    """§5.3's comparison. Pure, so a replay reaches the same verdict.

    A missing or non-positive input returns `UNVERIFIED`, never `DISCREPANCY`:
    absence of evidence is not evidence of a parser error, and marking it one
    would suppress a symbol for having no bar on file.
    """
    if tr_factor is None:
        return Verification(UNVERIFIED, reason="no tr_factor to test")
    if prev_close is None or ex_open is None:
        return Verification(UNVERIFIED, reason="no price pair for the ex-date")
    if prev_close <= 0 or ex_open <= 0:
        return Verification(
            UNVERIFIED, reason="a non-positive price is a symbol that did not trade"
        )
    expected = prev_close * tr_factor
    if expected <= 0:
        return Verification(UNVERIFIED, reason="the factor predicts a non-positive price")

    try:
        observed_gap = (ex_open / prev_close).quantize(_DEVIATION_DP)
        deviation = (ex_open / expected - Decimal(1)).quantize(_DEVIATION_DP)
    except (DivisionByZero, InvalidOperation):  # pragma: no cover - guarded above
        return Verification(UNVERIFIED, reason="the comparison is not computable")

    return Verification(
        VERIFIED if abs(deviation) <= TOLERANCE else DISCREPANCY,
        observed_gap=observed_gap,
        expected_gap=(expected / prev_close).quantize(_DEVIATION_DP),
        deviation=deviation,
    )


# ─── Composite events: one ex-date, several rows ────────────────────────────


@dataclass(frozen=True)
class CombinedFactor:
    """The single factor the market actually gaps by on one symbol's ex-date."""

    price_factor: Decimal | None = None
    dividend_per_share: Decimal | None = None
    reason: str | None = None


def combine(parsed: Sequence[ca_parser.ParsedAction]) -> CombinedFactor:
    """Compose every action landing on one symbol's ex-date into one factor.

    §5.3 handles the composite case *within* one purpose string — "SUB-DIVISION
    FROM RS 10 TO RS 2 AND BONUS IN 1:1 RATIO". Measured over the backfilled
    history, that is not the shape composites actually arrive in: NSE publishes
    them as **separate feed rows sharing a symbol and an ex-date**, each with
    its own clean single-action string.

    Sixteen of the twenty-two discrepancies in the first run over the history
    were this, and each looked catastrophic — DELPHIFX read as a 2:1 bonus alone
    predicts a 67% gap where the market took 93%, a deviation of -79%. Composed,
    the same event verifies at +4.5%. Nothing was wrong with either parse; the
    error was verifying half an event.

    Multiplication is commutative, so §5.3's execution order does not change the
    product; it is preserved in `COMPOSITION_ORDER` for the string case where it
    does matter. A single action composes to itself, so there is one code path.

    If any action on the date states no factor, the combined factor is unknown
    and its siblings cannot be verified either — R6, suppress rather than guess.
    """
    price = Decimal(1)
    dividend = Decimal(0)
    for action in parsed:
        if action.price_factor is None:
            return CombinedFactor(
                reason=(
                    f"a {action.action_type} action on the same ex-date states no "
                    "factor, so the combined gap is unknowable"
                )
            )
        price *= action.price_factor
        if action.dividend_per_share is not None:
            dividend += action.dividend_per_share
    return CombinedFactor(
        price_factor=price, dividend_per_share=dividend if dividend else None
    )


def combined_tr_factor(
    parsed: Sequence[ca_parser.ParsedAction], prev_close: Decimal | None
) -> Decimal | None:
    """The TRI factor for a whole ex-date event.

    Routed through `ca_parser.tr_factor` on a synthetic composite so that the
    §5.3 formula has exactly one implementation — a second copy here would be
    free to drift from the one task 1.3 writes into the column.
    """
    combined = combine(parsed)
    if combined.price_factor is None:
        return None
    return ca_parser.tr_factor(
        ca_parser.ParsedAction(
            action_type=ca_parser.COMPOSITE,
            price_factor=combined.price_factor,
            dividend_per_share=combined.dividend_per_share,
        ),
        prev_close,
    )


# ─── Prices ─────────────────────────────────────────────────────────────────


class PriceSource(Protocol):
    """Somewhere a symbol's session on a date can be read from."""

    def bar(self, symbol: str, day: date) -> Bar | None: ...


@dataclass(frozen=True)
class PricePair:
    """The two prices §5.3's comparison needs, and how they were obtained."""

    prev_date: date | None = None
    prev_close: Decimal | None = None
    ex_open: Decimal | None = None
    exchange_prev_close: Decimal | None = None
    prev_close_disagrees: bool = False
    reason: str | None = None


def price_pair(
    prices: PriceSource, calendar: TradingCalendar, symbol: str, ex_date: date
) -> PricePair:
    """The as-traded close before an ex-date and the open on it.

    Calendar-driven, never date arithmetic (§5.2): "the previous trading day" is
    not "yesterday", and reading the wrong session's close puts an otherwise
    correct factor a whole day out.

    The exchange's own `PrvsClsgPric` is read as well and compared. Measured, it
    is the as-traded close and agrees exactly — but if NSE ever pre-adjusted it,
    a verification built on it would compare an adjusted price against an
    adjusted expectation and confirm itself. The spec's source wins; the
    disagreement is recorded.
    """
    try:
        prev_date = previous_trading_day(ex_date, calendar)
    except (CalendarRangeError, KeyError):
        return PricePair(reason=f"{ex_date} has no previous trading day in the calendar")

    ex_bar = prices.bar(symbol, ex_date)
    prev_bar = prices.bar(symbol, prev_date)
    if ex_bar is None or prev_bar is None:
        missing = "ex-date" if ex_bar is None else "previous session"
        return PricePair(
            prev_date=prev_date,
            reason=f"no bar for {symbol} on the {missing}",
        )

    prev_close = prev_bar.close
    exchange_prev = ex_bar.prev_close
    disagrees = (
        prev_close is not None
        and exchange_prev is not None
        and prev_close > 0
        and abs(exchange_prev / prev_close - Decimal(1)) > Decimal("0.001")
    )
    return PricePair(
        prev_date=prev_date,
        prev_close=prev_close,
        ex_open=ex_bar.open,
        exchange_prev_close=exchange_prev,
        prev_close_disagrees=bool(disagrees),
    )


class DailyBarsPrices:
    """Prices from `daily_bars` — the source once task 2.1 has filled it."""

    def __init__(self, conn: sa.Connection) -> None:
        self._conn = conn
        self._cache: dict[tuple[str, date], Bar | None] = {}

    def bar(self, symbol: str, day: date) -> Bar | None:
        key = (symbol, day)
        if key not in self._cache:
            row = self._conn.execute(
                sa.text(
                    "SELECT symbol, date, series, open, high, low, close, prev_close, "
                    "volume, turnover, trades FROM daily_bars "
                    "WHERE symbol = :symbol AND date = :day"
                ),
                {"symbol": symbol, "day": day},
            ).mappings().first()
            self._cache[key] = (
                Bar(
                    symbol=row["symbol"],
                    date=row["date"],
                    series=row["series"] or "",
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    prev_close=row["prev_close"],
                    last=None,
                    volume=row["volume"],
                    turnover=row["turnover"],
                    trades=row["trades"],
                )
                if row is not None
                else None
            )
        return self._cache[key]


class CachedBhavcopyPrices:
    """Prices read straight off the Phase 0 backfill.

    §5.3's claim is that verification "catches parser errors using data already
    on disk", and this is that data. One file is parsed per date and held, so a
    run over the whole history reads each of the 244 cached files once rather
    than once per action.
    """

    def __init__(self, cache_root: Path) -> None:
        self._root = Path(cache_root) / BHAVCOPY_CACHE_DIR
        self._day = lru_cache(maxsize=None)(self._load_day)

    def _load_day(self, day: date) -> dict[str, Bar]:
        directory = self._root / day.isoformat()
        if not directory.is_dir():
            return {}
        for path in sorted(directory.glob("*.zip")):
            payload = read_cached(path)
            if payload is None:
                log.warning("cached bhavcopy for %s failed its digest check", day)
                continue
            return {bar.symbol: bar for bar in read_bhavcopy(payload)}
        return {}

    def bar(self, symbol: str, day: date) -> Bar | None:
        return self._day(day).get(symbol)

    @property
    def cached_dates(self) -> list[date]:
        if not self._root.is_dir():
            return []
        days = []
        for child in self._root.iterdir():
            if not child.is_dir() or not any(child.glob("*.zip")):
                continue
            try:
                days.append(date.fromisoformat(child.name))
            except ValueError:
                continue
        return sorted(days)


# ─── The job ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActionToVerify:
    """One `corporate_actions` row, as the job reads it."""

    id: int
    symbol: str
    ex_date: date
    action_type: str
    purpose_raw: str
    price_factor: Decimal | None
    verification: str


@dataclass
class VerifyReport:
    """What a run decided, in the shape the acceptance criterion is stated in."""

    start: date
    end: date
    considered: int = 0
    composite_events: int = 0
    verdicts: Counter[str] = field(default_factory=Counter)
    tr_factor_filled: int = 0
    unverifiable_reasons: Counter[str] = field(default_factory=Counter)
    prev_close_disagreements: list[str] = field(default_factory=list)
    price_source: str = ""

    @property
    def testable(self) -> int:
        """Rows the market could actually settle — the acceptance denominator."""
        return self.verdicts[VERIFIED] + self.verdicts[DISCREPANCY]

    @property
    def verified_ratio(self) -> float:
        return self.verdicts[VERIFIED] / self.testable if self.testable else 0.0

    def log(self) -> None:
        log.info(
            "CA verification %s to %s over %s: %d actions considered",
            self.start,
            self.end,
            self.price_source,
            self.considered,
        )
        for verdict in (VERIFIED, DISCREPANCY, UNVERIFIED):
            if self.verdicts[verdict]:
                log.info("  %-12s %5d", verdict, self.verdicts[verdict])
        if self.composite_events:
            log.info(
                "  %d ex-dates carried more than one action and were verified "
                "against the combined factor (§5.3)",
                self.composite_events,
            )
        log.info(
            "  verified / testable = %d/%d = %.4f",
            self.verdicts[VERIFIED],
            self.testable,
            self.verified_ratio,
        )
        if self.tr_factor_filled:
            log.info(
                "  %d tr_factor values completed from the previous close (§5.3)",
                self.tr_factor_filled,
            )
        for reason, count in self.unverifiable_reasons.most_common(8):
            log.info("    unverifiable: %4d  %s", count, reason)
        for line in self.prev_close_disagreements[:5]:
            log.warning("  exchange previous close disagrees: %s", line)


_SELECT_ACTIONS = sa.text(
    """
    SELECT id, symbol, ex_date, action_type, purpose_raw, price_factor, verification
    FROM corporate_actions
    WHERE ex_date BETWEEN :start AND :end
    ORDER BY ex_date, symbol
    """
)

_UPDATE_VERDICT = sa.text(
    """
    UPDATE corporate_actions
    SET verification = :verification,
        observed_gap = :observed_gap,
        tr_factor    = COALESCE(:tr_factor, tr_factor)
    WHERE id = :id
    """
)


def verify_actions(
    actions: Sequence[ActionToVerify],
    prices: PriceSource,
    calendar: TradingCalendar,
    report: VerifyReport,
) -> list[dict[str, object]]:
    """Settle each action against the market. Returns the updates to write.

    Grouped by (symbol, ex_date) first, because that is the unit the market
    settles: several actions on one date gap the price by their product, and
    testing each against its own factor alone fails all of them. See `combine`.

    An `UNPARSED` row receives no verdict — it carries no factor to test, and
    recovering it is task 1.5's job by a different route. It still counts
    towards its siblings' combined factor, so an unreadable string on a date
    leaves the whole event unverifiable rather than silently half-tested.
    """
    updates: list[dict[str, object]] = []
    events: dict[tuple[str, date], list[ActionToVerify]] = {}
    for action in actions:
        events.setdefault((action.symbol, action.ex_date), []).append(action)

    for (symbol, ex_date), group in events.items():
        testable = [
            action
            for action in group
            if action.action_type != ca_parser.UNPARSED
            and action.price_factor is not None
            # An inferred factor was snapped *from* this ex-date gap (task 1.5),
            # so testing it against that same gap confirms nothing — it would
            # verify by construction, and the confirmation would be circular.
            # Worse, it would overwrite the INFERRED verdict that §5.3 requires
            # be "flagged everywhere it appears", laundering a snapped guess
            # into two sources agreeing. Only the text produces a claim the
            # market can independently settle.
            and action.verification != INFERRED
        ]
        if not testable:
            continue
        report.considered += len(testable)
        if len(group) > 1:
            report.composite_events += 1

        pair = price_pair(prices, calendar, symbol, ex_date)
        if pair.prev_close_disagrees:
            report.prev_close_disagreements.append(
                f"{symbol} {ex_date}: exchange {pair.exchange_prev_close} "
                f"vs previous session {pair.prev_close}"
            )

        # The dividend term is recovered by re-reading the stored purpose strings
        # rather than from a column: the parser is pure, so this is the same
        # answer task 1.3 would have produced had a previous close existed then.
        parsed = [ca_parser.parse(action.purpose_raw) for action in group]
        combined = combine(parsed)
        tr = combined_tr_factor(parsed, pair.prev_close)

        result = verify(tr_factor=tr, prev_close=pair.prev_close, ex_open=pair.ex_open)
        for action in testable:
            report.verdicts[result.verification] += 1
            if result.verification == UNVERIFIED:
                report.unverifiable_reasons[
                    combined.reason or pair.reason or result.reason or "unstated"
                ] += 1

            # Each row keeps its own tr_factor — the column describes that
            # action, not the event. The combined factor is what the verdict was
            # reached on, and it is the event that is verified or not.
            own = ca_parser.tr_factor(
                ca_parser.parse(action.purpose_raw), pair.prev_close
            )
            if own is not None:
                report.tr_factor_filled += 1
            updates.append(
                {
                    "id": action.id,
                    "verification": result.verification,
                    "observed_gap": result.observed_gap,
                    "tr_factor": own,
                }
            )
    return updates


def run(
    *,
    start: date,
    end: date,
    cache_root: Path | None = None,
    price_source: str = "auto",
    dry_run: bool = False,
    engine: sa.Engine | None = None,
) -> VerifyReport:
    """Verify every parsed action with an ex-date in [start, end]."""
    from app.config import get_settings

    cache_root = Path(cache_root or get_settings().cache_root)
    engine = engine or get_engine()
    report = VerifyReport(start=start, end=end)

    with engine.connect() as conn:
        calendar = load_trading_calendar(conn, start - timedelta(days=30), end)
        actions = [
            ActionToVerify(*row)
            for row in conn.execute(_SELECT_ACTIONS, {"start": start, "end": end}).all()
        ]
        prices, report.price_source = choose_price_source(conn, cache_root, price_source)
        updates = verify_actions(actions, prices, calendar, report)

    if dry_run:
        log.info("--dry-run: nothing written")
        report.log()
        return report

    with engine.begin() as conn:
        if updates:
            conn.execute(_UPDATE_VERDICT, updates)
    report.log()
    return report


def choose_price_source(
    conn: sa.Connection, cache_root: Path, requested: str
) -> tuple[PriceSource, str]:
    """Pick where prices come from, and return it with a description of itself.

    `auto` prefers `daily_bars` once it holds rows and reads the backfill cache
    otherwise. The choice is logged either way: a job that silently changed its
    evidence base between runs would make two different verdicts look like one.

    Shared with `ca_infer` rather than duplicated. Two jobs free to disagree
    about where prices come from would be two jobs free to disagree about a
    factor, and they write to the same column.
    """
    if requested not in ("auto", "daily_bars", "cache"):
        raise ValueError(f"unknown price source {requested!r}")
    if requested != "cache":
        bars = conn.execute(sa.text("SELECT COUNT(*) FROM daily_bars")).scalar_one()
        if bars:
            log.info("reading prices from daily_bars")
            return DailyBarsPrices(conn), f"daily_bars ({bars} rows)"
        if requested == "daily_bars":
            raise ValueError("daily_bars is empty; run the bhavcopy ingest or use --prices cache")
    source = CachedBhavcopyPrices(cache_root)
    dates = source.cached_dates
    log.info(
        "reading prices from the cached bhavcopy backfill, %d sessions %s to %s "
        "(daily_bars is empty until task 2.1)",
        len(dates),
        dates[0] if dates else "-",
        dates[-1] if dates else "-",
    )
    return source, f"cached bhavcopy ({len(dates)} sessions)"


def discrepancies(conn: sa.Connection, limit: int = 200) -> list[dict[str, object]]:
    """The rows `/api/eval/unparsed-actions` lists — §16, BUILD_PLAN 1.4.

    Both halves of the honest answer to "how far can string parsing be trusted":
    the strings that did not parse, and the factors the market contradicted.
    """
    rows = conn.execute(
        sa.text(
            """
            SELECT symbol, ex_date, action_type, purpose_raw, ratio_text,
                   price_factor, tr_factor, observed_gap, verification
            FROM corporate_actions
            WHERE verification IN ('UNPARSED', 'DISCREPANCY')
            ORDER BY verification, ex_date DESC, symbol
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings()
    return [dict(row) for row in rows]


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify CA factors (§5.3).")
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        help="Earliest ex-date. Default: yesterday, the §19.1 morning job.",
    )
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--history",
        action="store_true",
        help="Verify the whole backfilled history rather than yesterday.",
    )
    parser.add_argument("--prices", choices=("auto", "daily_bars", "cache"), default="auto")
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s %(message)s"
    )
    today = datetime.now(tz=IST).date()
    if args.history:
        from app.config import get_settings
        from app.ingest.calendar import earliest_cached_session

        start = args.start or earliest_cached_session(
            Path(args.cache_root or get_settings().cache_root)
        )
        if start is None:
            log.error("no cached bhavcopy; run `make backfill` first")
            return 1
        end = args.end or today
    else:
        # §19.1: 07:15, for yesterday's ex-dates.
        start = args.start or today - timedelta(days=1)
        end = args.end or start

    try:
        run(
            start=start,
            end=end,
            cache_root=args.cache_root,
            price_source=args.prices,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        log.error("CA verification failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


def float_tolerance() -> float:
    """CA_VERIFY_TOLERANCE as a JSON number, for the eval endpoint.

    The endpoint publishes the band its verdicts were made against, so a reader
    can tell a tight test from a loose one rather than taking the ratio on
    trust. R1: the value still comes from §21 and only from there.
    """
    return float(CA_VERIFY_TOLERANCE)
