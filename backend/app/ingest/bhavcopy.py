"""UDiFF bhavcopy reader — docs/BUILD_SPEC.md §6, BUILD_PLAN tasks 1.4 and 2.1.

Bytes to typed bars, and nothing else. No database, no validation verdicts, no
quarantine, no `ingest_runs` — that contract is task 2.1's, and it will be built
on top of this rather than beside it.

This exists now because task 1.4 verifies parsed corporate-action factors
against the ex-date price gap, and §5.3 is explicit that the market is the
second source: "this catches parser errors, wrong ratios, and missed composite
actions using data already on disk". The data already on disk is the Phase 0
backfill, and something has to read it.

─── What the columns are, as verified ───────────────────────────────────────

R3 forbids guessing market-data semantics, so the two that matter here were
measured rather than assumed, on 6 September 2026 across eight ex-dates with a
known bonus or split:

  `PrvsClsgPric` on an ex-date is the **as-traded** previous close, not the
  adjusted one. Compared against the previous trading day's `ClsPric` it came
  back at a ratio of exactly 1.0000 on all eight. Had NSE pre-adjusted it, every
  verification in `ca_verify` would have been comparing an adjusted price
  against an adjusted expectation and confirming itself.

  `TtlTrfVal` is turnover in rupees, which is what R9 requires every statistic
  to use. `TtlTradgVol` is share count and may be displayed but never fed into a
  z-score, a baseline or a liquidity threshold.

A row's `SctySrs` is the series, and §2.1 puts EQ, BE and BZ in scope. The file
also carries index rows, ETFs, government bonds and SME series, which is why
`read_bhavcopy` filters rather than trusting the caller to.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# §2.1: NSE cash equities, EQ / BE / BZ series.
IN_SCOPE_SERIES = ("EQ", "BE", "BZ")

TRADE_DATE_FORMAT = "%Y-%m-%d"


class BhavcopyError(ValueError):
    """The payload is not a readable bhavcopy."""


# Source label written to `ingest_runs` and `daily_bars.source` — imported by
# the ingest orchestrator so there is one spelling, not two.
BHAVCOPY_SOURCE = "bhavcopy"


@dataclass(frozen=True)
class Bar:
    """One symbol's session, as traded. Prices are unadjusted.

    Every field is `Decimal` or `int`, never `float`: turnover in paise exceeds
    2**53, where float silently loses integer precision, and `canonical.py`
    already refuses to hash a value whose repr is not stable.
    """

    symbol: str
    date: date
    series: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    prev_close: Decimal | None
    last: Decimal | None
    volume: int | None
    turnover: Decimal | None
    trades: int | None


def _decimal(raw: str | None) -> Decimal | None:
    text = (raw or "").strip()
    if not text or text == "-":
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _int(raw: str | None) -> int | None:
    value = _decimal(raw)
    return int(value) if value is not None else None


def _rows(payload: bytes) -> Iterable[dict[str, str]]:
    """The CSV rows inside a bhavcopy, zipped or not.

    NSE publishes the UDiFF bhavcopy as a one-entry zip. Accepting the plain CSV
    too keeps fixtures readable without a zip round trip in every test.
    """
    if payload[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not names:
                raise BhavcopyError("zip contains no CSV")
            text = archive.read(names[0]).decode("utf-8")
    else:
        text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise BhavcopyError("bhavcopy has no header row")
    reader.fieldnames = [name.strip() for name in reader.fieldnames]
    return reader


def read_bhavcopy(payload: bytes, *, series: Iterable[str] = IN_SCOPE_SERIES) -> list[Bar]:
    """Parse a bhavcopy into in-scope bars.

    Rows whose trade date does not parse are skipped rather than dated by the
    filename: `docs/data-notes.md` records the delivery endpoint serving one
    date's rows under another's name, and a bar filed under the wrong date is
    the same failure in a more damaging place.
    """
    wanted = set(series)
    bars: list[Bar] = []
    for row in _rows(payload):
        symbol = (row.get("TckrSymb") or "").strip()
        row_series = (row.get("SctySrs") or "").strip()
        if not symbol or row_series not in wanted:
            continue
        try:
            trade_date = datetime.strptime(
                (row.get("TradDt") or "").strip(), TRADE_DATE_FORMAT
            ).date()
        except ValueError:
            continue
        bars.append(
            Bar(
                symbol=symbol,
                date=trade_date,
                series=row_series,
                open=_decimal(row.get("OpnPric")),
                high=_decimal(row.get("HghPric")),
                low=_decimal(row.get("LwPric")),
                close=_decimal(row.get("ClsPric")),
                prev_close=_decimal(row.get("PrvsClsgPric")),
                last=_decimal(row.get("LastPric")),
                volume=_int(row.get("TtlTradgVol")),
                # Rupees, not share count — R9.
                turnover=_decimal(row.get("TtlTrfVal")),
                trades=_int(row.get("TtlNbOfTxsExctd")),
            )
        )
    return bars


def content_date(bars: Iterable[Bar]) -> date | None:
    """The trading date a file's rows actually carry.

    The bhavcopy equivalent of the `DATE1` check the Phase 0 backfill runs on
    the delivery file. A file whose rows disagree with each other has no single
    content date and returns None.
    """
    dates = {bar.date for bar in bars}
    return dates.pop() if len(dates) == 1 else None
