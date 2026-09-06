"""CA factor inference for the unparsed tail — §5.3, BUILD_PLAN task 1.5.

Verification (task 1.4) runs in one direction: parse first, then check against
the ex-date gap. §5.3 points out that it also runs in the other. If a
`corporate_actions` row exists for `(symbol, ex_date)` — so we know an action
occurred — but the purpose string did not parse, the observed gap is itself an
estimate of the factor:

    observed_gap = open(symbol, ex_date) / close(symbol, previous_trading_day)
    snapped      = nearest(CA_CLEAN_FACTORS, observed_gap)

    if abs(observed_gap / snapped - 1.0) <= CA_INFER_SNAP_TOLERANCE:
        price_factor = snapped
        verification = 'INFERRED'     # usable, but flagged everywhere it appears
    else:
        verification = 'UNPARSED'     # suppress

`CA_CLEAN_FACTORS` is a lookup table, not a parser. Nothing here computes a
factor; it only chooses which of eighteen standard ratios an action already
known to have happened most likely was.

─── The guard, which is the entire safety argument ──────────────────────────

§5.3, in as many words:

> Without that guard a genuine -50% crash would be silently reinterpreted as a
> 1:1 bonus, which is the worst failure this system can produce. With it, we are
> only choosing *which* clean ratio applies to an action we already know
> happened.

So this module iterates over **scheduled actions** and asks what factor each
had. It never iterates over price gaps asking whether an action occurred. That
makes the guard structural rather than a check that could be forgotten: there is
no code path from a price movement to a new `corporate_actions` row, and
`actions_on` exists so callers can assert that absence directly.

Note also that the two defences are independent. A -48% fall is a gap of 0.52,
which is 4% from the nearest clean factor against a 2% band — so even without
the guard it would not snap. The guard is what protects the -49.5% fall, which
would.

─── Attribution across a composite ex-date ──────────────────────────────────

Task 1.4 established that one ex-date can carry several actions and that the
market gaps by their product. Inferring an unknown factor from the whole gap
would attribute the entire move to it, so any sibling whose factor is known is
divided out first and the residual is what gets snapped. Two unreadable actions
on one date are left alone: their residual is a product with no way to say which
half belongs to which, and splitting it arbitrarily is exactly the invention
this module exists to avoid.

    python -m app.ingest.ca_infer --history
    python -m app.ingest.ca_infer --history --dry-run
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
from pathlib import Path

import sqlalchemy as sa

from app.constants import CA_CLEAN_FACTORS, CA_INFER_SNAP_TOLERANCE
from app.db import get_engine
from app.ingest import ca_parser, ca_verify
from app.ingest.calendar import load_trading_calendar
from app.timeutil import IST

log = logging.getLogger(__name__)

SOURCE = "ca_infer"

INFERRED = ca_verify.INFERRED
UNPARSED = ca_verify.UNPARSED

SNAP_TOLERANCE = Decimal(str(CA_INFER_SNAP_TOLERANCE))
# NUMERIC(18,10), the same grid `ca_parser` quantises its factors onto, so an
# inferred 1/3 and a parsed 1/3 are the same value in the column.
FACTOR_DP = Decimal(1).scaleb(-10)

# §21's table, on that grid and ordered. `1/6`, `1/3`, `2/3` and `5/6` arrive as
# floats; `repr` keeps every digit Python has before the quantise rounds.
CLEAN_FACTORS: tuple[Decimal, ...] = tuple(
    sorted({Decimal(repr(factor)).quantize(FACTOR_DP) for factor in CA_CLEAN_FACTORS})
)

_DISTANCE_DP = Decimal("0.000001")


# Why a candidate was declined, as a fixed code. The prose reason embeds the
# gap, which makes every message unique and a tally of them useless; the report
# groups on the code and prints the prose for individual rows.
NO_GAP = "NO_OBSERVED_GAP"
NON_POSITIVE_GAP = "NON_POSITIVE_GAP"
TOO_FAR = "NO_CLEAN_FACTOR_WITHIN_TOLERANCE"
MULTIPLE_UNATTRIBUTED = "MULTIPLE_UNATTRIBUTED_ACTIONS"
SIBLING_NOT_DIVISIBLE = "SIBLING_FACTOR_NOT_DIVISIBLE"


@dataclass(frozen=True)
class Inference:
    """What the price gap says the factor was, and whether that is usable."""

    verification: str
    price_factor: Decimal | None = None
    snapped_to: Decimal | None = None
    distance: Decimal | None = None
    reason: str | None = None
    code: str | None = None


def snap_factor(observed_gap: Decimal | None) -> Inference:
    """Choose the clean ratio an observed gap is closest to, if any is close.

    Distance is relative, not absolute. The table spans 0.1 to 10.0, so absolute
    distance would make every large gap look nearest 10.0 — and §5.3's own
    acceptance test is `observed / snapped - 1`, so the search uses that measure
    and the two cannot disagree about which entry won.

    There is deliberately no 1.0 in the table: "no adjustment" is not a ratio to
    be recovered from a price that barely moved, and adding the entry to shrink
    the unparsed tail would break R1.
    """
    if observed_gap is None:
        return Inference(UNPARSED, reason="no observed gap for the ex-date", code=NO_GAP)
    if observed_gap <= 0:
        return Inference(
            UNPARSED, reason="a non-positive gap is not a factor", code=NON_POSITIVE_GAP
        )

    best: Decimal | None = None
    best_distance: Decimal | None = None
    for candidate in CLEAN_FACTORS:
        try:
            distance = abs(observed_gap / candidate - Decimal(1)).quantize(_DISTANCE_DP)
        except (DivisionByZero, InvalidOperation):  # pragma: no cover - table is positive
            continue
        if best_distance is None or distance < best_distance:
            best, best_distance = candidate, distance

    if best is None or best_distance is None:  # pragma: no cover - table is non-empty
        return Inference(
            UNPARSED, reason="no clean factor to compare against", code=TOO_FAR
        )
    if best_distance > SNAP_TOLERANCE:
        return Inference(
            UNPARSED,
            snapped_to=best,
            distance=best_distance,
            reason=(
                f"gap {observed_gap} is {best_distance} from the nearest clean "
                f"factor {best}, beyond the {SNAP_TOLERANCE} snap tolerance"
            ),
            code=TOO_FAR,
        )
    return Inference(
        INFERRED, price_factor=best, snapped_to=best, distance=best_distance
    )


def infer_one(
    *,
    observed_gap: Decimal | None,
    known_factor: Decimal | None,
    unattributed: int,
) -> Inference:
    """Snap the part of an ex-date gap that is not already accounted for.

    `known_factor` is the combined factor of the actions on that date whose
    factors are known; dividing it out leaves the residual belonging to the one
    that is not. `unattributed` is how many rows on the date are competing for
    that residual — more than one and it cannot be assigned at all.
    """
    if unattributed > 1:
        return Inference(
            UNPARSED,
            reason=(
                f"more than one action on this ex-date states no factor "
                f"({unattributed}), so the residual gap cannot be attributed"
            ),
            code=MULTIPLE_UNATTRIBUTED,
        )
    if observed_gap is None:
        return Inference(UNPARSED, reason="no observed gap for the ex-date", code=NO_GAP)
    residual = observed_gap
    if known_factor is not None:
        if known_factor <= 0:
            return Inference(
                UNPARSED,
                reason="a sibling factor of zero cannot be divided out",
                code=SIBLING_NOT_DIVISIBLE,
            )
        try:
            residual = observed_gap / known_factor
        except (DivisionByZero, InvalidOperation):  # pragma: no cover - guarded
            return Inference(
                UNPARSED,
                reason="the residual gap is not computable",
                code=SIBLING_NOT_DIVISIBLE,
            )
    return snap_factor(residual)


# ─── The job ────────────────────────────────────────────────────────────────


@dataclass
class InferReport:
    """What a run recovered, and what it declined to."""

    start: date
    end: date
    candidates: int = 0
    inferred: int = 0
    still_unparsed: int = 0
    reasons: Counter[str] = field(default_factory=Counter)
    recovered: list[str] = field(default_factory=list)
    nearest_misses: list[tuple[Decimal, str]] = field(default_factory=list)
    price_source: str = ""

    def log(self) -> None:
        log.info(
            "CA inference %s to %s over %s: %d unparsed actions considered",
            self.start,
            self.end,
            self.price_source,
            self.candidates,
        )
        # §19.2 names this metric; logged under that name so the operator sees
        # the same string here and on the dashboard.
        log.info("  swl_ca_inferred_total  %5d", self.inferred)
        log.info("  swl_ca_unparsed_total  %5d  (after inference)", self.still_unparsed)
        for line in self.recovered[:20]:
            log.info("    recovered %s", line)
        for code, count in self.reasons.most_common():
            log.info("    declined %-34s %4d", code, count)
        # The near misses are what a human would want to look at first: they are
        # the rows a slightly wider band would have recovered, and seeing them
        # is how one would tell a tolerance that is too tight from a tail that
        # genuinely has no clean answer.
        for _, line in sorted(self.nearest_misses)[:5]:
            log.info("    nearest miss: %s", line)


_SELECT_WINDOW = sa.text(
    """
    SELECT id, symbol, ex_date, action_type, purpose_raw, price_factor, verification
    FROM corporate_actions
    WHERE ex_date BETWEEN :start AND :end
    ORDER BY ex_date, symbol
    """
)

_UPDATE_INFERRED = sa.text(
    """
    UPDATE corporate_actions
    SET price_factor = :price_factor,
        tr_factor    = COALESCE(tr_factor, :price_factor),
        observed_gap = :observed_gap,
        verification = 'INFERRED'
    WHERE id = :id AND price_factor IS NULL
    """
)


def actions_on(conn: sa.Connection, symbol: str, ex_date: date) -> list[int]:
    """The scheduled corporate actions on one symbol's date.

    The guard, made queryable. §5.3's rule is that a factor may only be inferred
    when an action is already known to have happened, and this is how a caller —
    or a test asserting that a -48% crash was left alone — checks that directly
    rather than inferring it from the absence of an effect.
    """
    return list(
        conn.execute(
            sa.text(
                "SELECT id FROM corporate_actions WHERE symbol = :s AND ex_date = :d"
            ),
            {"s": symbol, "d": ex_date},
        ).scalars()
    )


def run(
    *,
    start: date,
    end: date,
    cache_root: Path | None = None,
    price_source: str = "auto",
    dry_run: bool = False,
    engine: sa.Engine | None = None,
    conn: sa.Connection | None = None,
) -> InferReport:
    """Recover what factors can be recovered for [start, end].

    `conn` lets a caller run this inside its own transaction — which is how the
    acceptance test mangles a real purpose string, watches it be recovered, and
    rolls the whole thing back without leaving the database changed.
    """
    from app.config import get_settings

    cache_root = Path(cache_root or get_settings().cache_root)
    report = InferReport(start=start, end=end)

    if conn is not None:
        updates = _plan(conn, start, end, cache_root, price_source, report)
        if not dry_run:
            _apply(conn, updates)
        report.log()
        return report

    engine = engine or get_engine()
    with engine.connect() as read_conn:
        updates = _plan(read_conn, start, end, cache_root, price_source, report)
    if not dry_run:
        with (engine or get_engine()).begin() as write_conn:
            _apply(write_conn, updates)
    else:
        log.info("--dry-run: nothing written")
    report.log()
    return report


def _apply(conn: sa.Connection, updates: Sequence[dict[str, object]]) -> None:
    if updates:
        # The WHERE clause re-checks that the factor is still absent, so
        # inference can only ever *fill* one and never replace one. A row task
        # 1.4 settled between the read and the write has a factor by
        # construction, so its empirical verdict cannot be overwritten by a
        # snapped guess — two sources agreeing outrank one.
        conn.execute(_UPDATE_INFERRED, list(updates))


def _plan(
    conn: sa.Connection,
    start: date,
    end: date,
    cache_root: Path,
    price_source: str,
    report: InferReport,
) -> list[dict[str, object]]:
    """Decide every update without writing any, so the read and write can sit in
    different transactions."""
    calendar = load_trading_calendar(conn, start - timedelta(days=30), end)
    rows = [
        ca_verify.ActionToVerify(*row)
        for row in conn.execute(_SELECT_WINDOW, {"start": start, "end": end}).all()
    ]
    # One price policy shared with verification, not a second copy of it.
    prices, report.price_source = ca_verify.choose_price_source(
        conn, cache_root, price_source
    )

    events: dict[tuple[str, date], list[ca_verify.ActionToVerify]] = {}
    for row in rows:
        events.setdefault((row.symbol, row.ex_date), []).append(row)

    updates: list[dict[str, object]] = []
    for (symbol, ex_date), group in events.items():
        # The candidates are exactly the rows §5.3 describes: an action is known
        # to have happened, and no factor came out of its purpose string.
        # An absent factor is the condition, not the verdict. A row already
        # marked INFERRED but holding no factor is in a state that asserts more
        # than it can show, and re-deriving it is how that gets repaired.
        candidates = [
            row
            for row in group
            if row.price_factor is None and row.verification in (UNPARSED, INFERRED)
        ]
        if not candidates:
            continue
        report.candidates += len(candidates)

        pair = ca_verify.price_pair(prices, calendar, symbol, ex_date)
        observed_gap = None
        if pair.prev_close and pair.ex_open and pair.prev_close > 0:
            observed_gap = (pair.ex_open / pair.prev_close).quantize(_DISTANCE_DP)

        known = [row for row in group if row.price_factor is not None]
        known_factor = None
        if known:
            known_factor = ca_verify.combined_tr_factor(
                [ca_parser.parse(row.purpose_raw) for row in known], pair.prev_close
            )

        result = infer_one(
            observed_gap=observed_gap,
            known_factor=known_factor,
            unattributed=len(candidates),
        )
        for row in candidates:
            if result.verification == INFERRED and result.price_factor is not None:
                report.inferred += 1
                report.recovered.append(
                    f"{symbol} {ex_date} gap {observed_gap} -> {result.price_factor} "
                    f"({result.distance} away): {row.purpose_raw[:48]}"
                )
                updates.append(
                    {
                        "id": row.id,
                        "price_factor": result.price_factor,
                        "observed_gap": observed_gap,
                    }
                )
            else:
                report.still_unparsed += 1
                report.reasons[result.code or NO_GAP] += 1
                report.nearest_misses.append(
                    (result.distance, f"{symbol} {ex_date} {row.action_type}: {result.reason}")
                    if result.distance is not None
                    else (Decimal(9), f"{symbol} {ex_date} {row.action_type}: {result.reason}")
                )
    return updates


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Infer CA factors (§5.3).")
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--history",
        action="store_true",
        help="Cover the whole backfilled history rather than yesterday.",
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
        log.error("CA inference failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
