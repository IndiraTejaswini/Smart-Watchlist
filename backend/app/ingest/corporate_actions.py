"""Corporate-action ingest — docs/BUILD_SPEC.md §5.3, BUILD_PLAN task 1.3.

Fetches NSE's corporate-action feed over the calendar window, reads each
`purpose_raw` through `ca_parser`, and writes `corporate_actions` with the
PRI/TRI split intact.

Why this runs before anything numerical (§5.3, last paragraph): after an
ex-bonus date a 1:1 bonus roughly halves the price while shareholder value is
unchanged. If this table is wrong, every return, volatility, beta and signal
downstream is wrong.

─── What this task does and does not decide ─────────────────────────────────

Three columns describe how much a factor can be trusted, and they are filled by
three different tasks:

    action_type / price_factor / tr_factor   here, from the text
    verification = VERIFIED | DISCREPANCY    task 1.4, from the ex-date gap
    verification = INFERRED                  task 1.5, for the unparsed tail

So every row this task writes lands as `UNVERIFIED` — parsed, not yet checked
against the market — or as `UNPARSED`, which §5.3's fail-safe rule suppresses.
Nothing here claims a factor is right; it claims only that the text said so.

─── tr_factor and the previous close ────────────────────────────────────────

§5.3 defines `tr_factor = price_factor x (prev - div) / prev`. For everything
except a cash payout there is no dividend term, so it equals `price_factor` and
is computed here. For a cash payout it needs the previous close, which lives in
`daily_bars` — a Phase 2 table. Until that exists the column stays NULL and the
run reports how many rows are waiting, rather than storing a guess. The amount
itself is never lost: `purpose_raw` is stored NOT NULL and the parser is pure,
so task 1.4 recovers it by re-reading the same string and gets the same answer.

    python -m app.ingest.corporate_actions
    python -m app.ingest.corporate_actions --from-cache-only
    python -m app.ingest.corporate_actions --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.constants import CA_INGEST_CHUNK_DAYS
from app.db import get_engine
from app.ingest import ca_parser, runs
from app.ingest.calendar import FORWARD_DAYS, earliest_cached_session
from app.ingest.nse_client import (
    CacheMissError,
    NSEClient,
    NSEError,
    sha256_bytes,
)
from app.ingest.symbol_master import CACHE_NAMESPACE, latest_cached_snapshot
from app.timeutil import IST

log = logging.getLogger(__name__)

# ─── Source ─────────────────────────────────────────────────────────────────

SOURCE = "corporate_actions"
NSE_HOME = "https://www.nseindia.com"
CA_URL = (
    NSE_HOME + "/api/corporates-corporateActions?index=equities"
    "&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}"
)
CA_REFERER = NSE_HOME + "/companies-listing/corporate-filings-actions"
CA_CACHE = "corporate_actions_{start:%Y%m%d}_{end:%Y%m%d}.json"

# The endpoint honours its date range but returns a bounded page, so the window
# is walked in chunks — R1: sourced from the registry.
CHUNK_DAYS = CA_INGEST_CHUNK_DAYS

NSE_DATE_FORMAT = "%d-%b-%Y"

# §5.3's verification enum. This task can only ever write the last two.
VERIFIED = "VERIFIED"
INFERRED = "INFERRED"
DISCREPANCY = "DISCREPANCY"
UNVERIFIED = "UNVERIFIED"
UNPARSED = "UNPARSED"


class CorporateActionsError(RuntimeError):
    """The corporate-action feed could not be obtained or made sense of."""


# ─── Records ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActionRow:
    """One corporate action, parsed and ready to write."""

    symbol: str
    ex_date: date
    record_date: date | None
    purpose_raw: str
    action_type: str
    ratio_text: str | None
    price_factor: Decimal | None
    tr_factor: Decimal | None
    verification: str


@dataclass(frozen=True)
class RejectedRow:
    """A feed row that cannot be written. §6.2 rule 5 — quarantined, not lost."""

    payload: dict[str, Any]
    reason: str


@dataclass
class LoadReport:
    """What a run did, in the shape §5.3 and task 1.6 ask about."""

    start: date
    end: date
    inputs_digest: str
    fetched: int = 0
    written: int = 0
    quarantined: int = 0
    action_type_counts: Counter[str] = field(default_factory=Counter)
    verification_counts: Counter[str] = field(default_factory=Counter)
    tr_factor_pending: int = 0
    unparsed_reasons: Counter[str] = field(default_factory=Counter)
    skipped_cached: bool = False

    @property
    def parse_coverage_ratio(self) -> float:
        """§19.2 `swl_ca_parse_coverage_ratio` — rows given a real action type."""
        total = sum(self.action_type_counts.values())
        if not total:
            return 0.0
        return (total - self.action_type_counts[ca_parser.UNPARSED]) / total

    def log(self) -> None:
        log.info(
            "corporate actions %s to %s: %d fetched, %d written, %d quarantined",
            self.start,
            self.end,
            self.fetched,
            self.written,
            self.quarantined,
        )
        for action_type in ca_parser.ACTION_TYPES:
            count = self.action_type_counts[action_type]
            if count:
                log.info("  action_type %-13s %5d", action_type, count)
        for verification in (VERIFIED, INFERRED, DISCREPANCY, UNVERIFIED, UNPARSED):
            count = self.verification_counts[verification]
            if count:
                log.info("  verification %-12s %5d", verification, count)
        log.info("  swl_ca_parse_coverage_ratio %.4f", self.parse_coverage_ratio)
        log.info(
            "  swl_ca_unparsed_total %d", self.action_type_counts[ca_parser.UNPARSED]
        )
        for reason, count in self.unparsed_reasons.most_common():
            log.info("    %4d  %s", count, reason)
        if self.tr_factor_pending:
            log.info(
                "  %d cash payouts have no tr_factor yet: it needs the previous "
                "close, and daily_bars is Phase 2 (§5.3)",
                self.tr_factor_pending,
            )


# ─── Parsing the feed ───────────────────────────────────────────────────────


def _parse_date(raw: str | None) -> date | None:
    if not raw or raw.strip() in ("", "-"):
        return None
    try:
        return datetime.strptime(raw.strip(), NSE_DATE_FORMAT).date()
    except ValueError:
        return None


def parse_feed(payload: bytes) -> list[dict[str, Any]]:
    """The corporate-action JSON -> its rows, whichever shape it arrives in."""
    document = json.loads(payload)
    if isinstance(document, list):
        return [row for row in document if isinstance(row, dict)]
    rows = document.get("data") if isinstance(document, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def build_rows(
    feed: Sequence[Mapping[str, Any]],
    *,
    prev_close: Mapping[tuple[str, date], Decimal] | None = None,
) -> tuple[list[ActionRow], list[RejectedRow]]:
    """Feed rows -> `corporate_actions` rows, plus what could not be written.

    `prev_close` supplies the close on the session before each ex-date, keyed
    `(symbol, ex_date)`. Empty until Phase 2 fills `daily_bars`, which is why
    a cash payout's `tr_factor` is NULL rather than wrong.
    """
    prev_close = prev_close or {}
    rows: list[ActionRow] = []
    rejected: list[RejectedRow] = []
    seen: set[tuple[str, date, str, str]] = set()

    for entry in feed:
        symbol = str(entry.get("symbol") or "").strip()
        purpose_raw = str(entry.get("subject") or "").strip()
        ex_date = _parse_date(entry.get("exDate"))
        if not symbol or not purpose_raw:
            rejected.append(RejectedRow(dict(entry), "MISSING_REQUIRED_FIELD"))
            continue
        if ex_date is None:
            # §4.3: an ex-date is matched on the IST trading date, and a row
            # without one can never be matched to a session at all.
            rejected.append(RejectedRow(dict(entry), "MISSING_OR_UNPARSED_EX_DATE"))
            continue

        parsed = ca_parser.parse(purpose_raw)
        key = (symbol, ex_date, parsed.action_type, purpose_raw)
        if key in seen:
            # The natural key is UNIQUE (symbol, ex_date, action_type,
            # purpose_raw); a repeat inside one payload is the feed listing the
            # same action twice, not two actions.
            continue
        seen.add(key)

        rows.append(
            ActionRow(
                symbol=symbol,
                ex_date=ex_date,
                record_date=_parse_date(entry.get("recDate")),
                purpose_raw=purpose_raw,
                action_type=parsed.action_type,
                ratio_text=parsed.ratio_text,
                price_factor=parsed.price_factor,
                tr_factor=ca_parser.tr_factor(
                    parsed, prev_close.get((symbol, ex_date))
                ),
                verification=verification_for(parsed),
            )
        )
    return rows, rejected


def verification_for(parsed: ca_parser.ParsedAction) -> str:
    """How far this row can be trusted, as of this task.

    `UNPARSED` covers both "the text was unreadable" and "the text was readable
    but states no factor for an action that moves the price" — a rights issue
    or a demerger. §5.3's fail-safe rule suppresses on either, and a row that
    said `UNVERIFIED` with a NULL factor would read as merely awaiting a check.
    """
    if parsed.action_type == ca_parser.UNPARSED:
        return UNPARSED
    if parsed.price_factor is None:
        return UNPARSED
    return UNVERIFIED


def inputs_digest(payloads: Mapping[str, bytes], window: tuple[date, date]) -> str:
    """One SHA-256 over every chunk plus the window — §6.2 rule 3."""
    digest = hashlib.sha256()
    digest.update(f"{window[0].isoformat()}:{window[1].isoformat()}".encode("ascii"))
    for name in sorted(payloads):
        digest.update(name.encode("utf-8"))
        digest.update(sha256_bytes(payloads[name]).encode("ascii"))
    return digest.hexdigest()


# ─── Fetching ───────────────────────────────────────────────────────────────


def fetch_feed(
    client: NSEClient, *, as_of: date, start: date, end: date
) -> dict[str, bytes]:
    """The corporate-action feed over [start, end], in cached chunks."""
    payloads: dict[str, bytes] = {}
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), end)
        filename = CA_CACHE.format(start=chunk_start, end=chunk_end)
        try:
            payload = client.fetch(
                CA_URL.format(start=chunk_start, end=chunk_end),
                source=CACHE_NAMESPACE,
                target_date=as_of,
                filename=filename,
                endpoint="corporate-actions",
                referer=CA_REFERER,
                accept_missing=True,
            )
        except (CacheMissError, NSEError) as exc:
            raise CorporateActionsError(
                f"corporate actions {chunk_start}..{chunk_end} unavailable: {exc}"
            ) from exc
        if payload is None:
            raise CorporateActionsError(
                f"corporate actions {chunk_start}..{chunk_end} returned nothing"
            )
        payloads[filename] = payload
        chunk_start = chunk_end + timedelta(days=1)
    return payloads


def load_previous_closes(
    conn: sa.Connection, rows: Sequence[ActionRow]
) -> dict[tuple[str, date], Decimal]:
    """The close on the last session before each ex-date, where one exists.

    Empty while `daily_bars` is empty, which is the state until Phase 2. Driven
    off the trading calendar rather than date arithmetic: "the previous trading
    day" is not "yesterday" (§5.2), and using the wrong session's close would
    put a verifiable factor a whole day out.
    """
    if not rows:
        return {}
    pairs = sorted({(row.symbol, row.ex_date) for row in rows})
    result = conn.execute(
        sa.text(
            """
            SELECT p.symbol, p.ex_date, b.close
            FROM (
                SELECT unnest(CAST(:symbols AS text[])) AS symbol,
                       unnest(CAST(:ex_dates AS date[])) AS ex_date
            ) p
            JOIN LATERAL (
                SELECT close FROM daily_bars d
                WHERE d.symbol = p.symbol AND d.date < p.ex_date
                ORDER BY d.date DESC LIMIT 1
            ) b ON TRUE
            """
        ),
        {
            "symbols": [symbol for symbol, _ in pairs],
            "ex_dates": [ex_date for _, ex_date in pairs],
        },
    ).all()
    closes: dict[tuple[str, date], Decimal] = {}
    for symbol, ex_date, close in result:
        if close is None:
            continue
        try:
            closes[(symbol, ex_date)] = Decimal(close)
        except InvalidOperation:  # pragma: no cover - NUMERIC is always decimal
            continue
    return closes


# ─── Loading ────────────────────────────────────────────────────────────────

_UPSERT_ACTION = sa.text(
    """
    INSERT INTO corporate_actions (
        symbol, ex_date, record_date, action_type, ratio_text, purpose_raw,
        price_factor, tr_factor, verification, source, ingested_at
    ) VALUES (
        :symbol, :ex_date, :record_date, :action_type, :ratio_text, :purpose_raw,
        :price_factor, :tr_factor, :verification, :source, NOW()
    )
    ON CONFLICT ON CONSTRAINT uq_corporate_actions_natural DO UPDATE SET
        record_date  = EXCLUDED.record_date,
        ratio_text   = EXCLUDED.ratio_text,
        -- An inferred factor did not come from the text and cannot be
        -- reproduced by re-reading it, so a re-parse has nothing better to
        -- offer and must not overwrite it. Without this the row keeps the
        -- INFERRED verdict below while losing the number that justified it —
        -- a row asserting a factor it no longer has, which is exactly the
        -- plausible-and-wrong state R5 exists to prevent. Task 1.5 recovers
        -- these from the ex-date gap; only task 1.5 may replace one.
        price_factor = CASE
            WHEN corporate_actions.verification = 'INFERRED'
            THEN corporate_actions.price_factor
            ELSE EXCLUDED.price_factor
        END,
        tr_factor    = CASE
            WHEN corporate_actions.verification = 'INFERRED'
            THEN corporate_actions.tr_factor
            ELSE EXCLUDED.tr_factor
        END,
        -- An empirical verdict outranks a re-parse. Task 1.4 writes VERIFIED,
        -- DISCREPANCY and INFERRED from the observed ex-date gap; re-running
        -- the parser must not quietly demote one of those back to UNVERIFIED.
        verification = CASE
            WHEN corporate_actions.verification IN ('VERIFIED','DISCREPANCY','INFERRED')
            THEN corporate_actions.verification
            ELSE EXCLUDED.verification
        END,
        ingested_at  = EXCLUDED.ingested_at
    """
)


def parse_coverage(conn: sa.Connection) -> Counter[str]:
    """§19.2 `swl_ca_parse_coverage_ratio`, read back from the database."""
    return Counter(
        {
            str(action_type): int(count)
            for action_type, count in conn.execute(
                sa.text(
                    "SELECT action_type, COUNT(*) FROM corporate_actions GROUP BY 1"
                )
            ).all()
        }
    )


def load(
    *,
    as_of: date,
    forward_days: int = FORWARD_DAYS,
    from_cache_only: bool = False,
    cache_root: Path | None = None,
    dry_run: bool = False,
    engine: sa.Engine | None = None,
) -> LoadReport:
    """Fetch, parse, and write corporate actions. One transaction (§6.2 r7)."""
    from app.config import get_settings

    cache_root = Path(cache_root or get_settings().cache_root)
    snapshot = as_of
    if from_cache_only:
        found = latest_cached_snapshot(cache_root, as_of)
        if found is None:
            raise CorporateActionsError(
                "--from-cache-only and no cached reference snapshot under "
                f"{cache_root / CACHE_NAMESPACE}"
            )
        snapshot = found
        log.info("reading the cached reference snapshot of %s", snapshot)

    start = earliest_cached_session(cache_root)
    if start is None:
        raise CorporateActionsError(
            f"no cached bhavcopy under {cache_root}; run `make backfill` first — "
            "the history window is defined by what was downloaded"
        )
    # Anchored to the snapshot, not to `as_of`. `fetch_feed` encodes the
    # window's chunk boundaries into each cache filename, so a window measured
    # from today slides one day every day and stops matching the files that
    # were written when the snapshot was taken — `--from-cache-only` then
    # fails on a chunk it has, under a name it no longer asks for. Outside
    # cache-only mode `snapshot` is `as_of`, so live fetches are unchanged.
    end = snapshot + timedelta(days=forward_days)

    with NSEClient(from_cache_only=from_cache_only, cache_root=cache_root) as client:
        payloads = fetch_feed(client, as_of=snapshot, start=start, end=end)

    feed: list[dict[str, Any]] = []
    for name in sorted(payloads):
        feed.extend(parse_feed(payloads[name]))

    digest = inputs_digest(payloads, (start, end))
    report = LoadReport(start=start, end=end, inputs_digest=digest)
    report.fetched = len(feed)

    engine = engine or get_engine()
    if dry_run:
        rows, rejected = build_rows(feed)
        _fill_report(report, rows, rejected)
        log.info("--dry-run: nothing written")
        report.log()
        return report

    with engine.begin() as conn:
        if runs.already_ingested(conn, source=SOURCE, target_date=snapshot, file_hash=digest):
            log.info("corporate-action inputs unchanged since the last run (§6.2 rule 3)")
            rows, rejected = build_rows(feed, prev_close=None)
            _fill_report(report, rows, rejected)
            runs.finish_run(
                conn,
                runs.start_run(conn, source=SOURCE, target_date=snapshot, file_hash=digest),
                status="SKIPPED_CACHED",
                rows=len(rows),
            )
            report.skipped_cached = True
            report.log()
            return report

        run_id = runs.start_run(conn, source=SOURCE, target_date=snapshot, file_hash=digest)
        # Two passes: the first to learn which (symbol, ex_date) pairs exist, the
        # second to attach the previous closes those pairs resolve to.
        draft, _ = build_rows(feed)
        rows, rejected = build_rows(feed, prev_close=load_previous_closes(conn, draft))
        _fill_report(report, rows, rejected)

        if rows:
            conn.execute(
                _UPSERT_ACTION,
                [
                    {
                        "symbol": row.symbol,
                        "ex_date": row.ex_date,
                        "record_date": row.record_date,
                        "action_type": row.action_type,
                        "ratio_text": row.ratio_text,
                        "purpose_raw": row.purpose_raw,
                        "price_factor": row.price_factor,
                        "tr_factor": row.tr_factor,
                        "verification": row.verification,
                        "source": SOURCE,
                    }
                    for row in rows
                ],
            )
        if rejected:
            conn.execute(
                sa.text(
                    "INSERT INTO ingest_quarantine "
                    "(ingest_run_id, source_file, raw_payload, rejection_reason) "
                    "VALUES (:run_id, :source_file, CAST(:payload AS JSONB), :reason)"
                ),
                [
                    {
                        "run_id": run_id,
                        "source_file": "corporates-corporateActions",
                        "payload": json.dumps(row.payload, sort_keys=True, default=str),
                        "reason": row.reason,
                    }
                    for row in rejected
                ],
            )
        runs.finish_run(conn, run_id, status="OK", rows=len(rows))
        report.written = len(rows)

    report.log()
    return report


def _fill_report(
    report: LoadReport, rows: Sequence[ActionRow], rejected: Sequence[RejectedRow]
) -> None:
    report.quarantined = len(rejected)
    report.action_type_counts = Counter(row.action_type for row in rows)
    report.verification_counts = Counter(row.verification for row in rows)
    report.tr_factor_pending = sum(
        1
        for row in rows
        if row.tr_factor is None and row.action_type != ca_parser.UNPARSED
    )
    report.unparsed_reasons = Counter(
        ca_parser.parse(row.purpose_raw).reason or "unstated"
        for row in rows
        if row.action_type == ca_parser.UNPARSED
    )


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest corporate actions (§5.3).")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--forward-days", type=int, default=FORWARD_DAYS)
    parser.add_argument(
        "--from-cache-only",
        action="store_true",
        help="Never touch the network; read the newest cached snapshot.",
    )
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse and report without writing."
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
    except CorporateActionsError as exc:
        log.error("corporate actions failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
