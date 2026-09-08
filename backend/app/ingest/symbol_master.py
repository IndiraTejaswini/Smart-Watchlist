"""Symbol master ingest — docs/BUILD_SPEC.md §5.1, BUILD_PLAN task 1.1.

Builds `instruments` from NSE's list of securities, resolves a sector for every
row through the §5.1 fallback chain, records which tier answered in
`sector_source`, and stitches renames into `symbol_aliases`.

The chain, verbatim from §5.1:

    1. NSE sector classification file        -> sector_source = PRIMARY_FILE
    2. Index constituent mapping             -> sector_source = INDEX_MAP
    3. Vendor/broker instrument metadata     -> sector_source = VENDOR
    4. 'UNASSIGNED'                          -> sector_source = UNASSIGNED

`UNASSIGNED` is never NULL, and it is not free: §11.3 cannot classify an
unassigned symbol `SECTOR_WIDE`, which biases it toward being surfaced. So
coverage is a tracked metric (`swl_sector_coverage_ratio`, §19.2) and this
module reports it on every run.

─── What each tier actually is, and how that was established ────────────────

R3 forbids guessing market-data semantics, so each tier below is a source that
was fetched and measured on 6 September 2026, not assumed. The full measurement
is in `docs/data-notes.md`; the short version:

  Tier 1  `ind_niftytotalmarket_list.csv` — NSE Indices' classification of the
          whole investable universe, and the broadest single NSE-published file
          carrying the official `Industry` column. 755 symbols.

  Tier 2  The remaining Nifty index constituent files, broad and sectoral. They
          are largely subsets of tier 1; measured, they add 3 symbols. Kept
          because that is the chain §5.1 specifies, and because index
          membership changes on a different schedule from the tier-1 file.

  Tier 3  BSE's company header (`ComHeadernew`), joined on ISIN. BSE publishes
          the same SEBI/AMFI sector taxonomy NSE's index files use — checked on
          150 symbols carried by both sources: 150 agreed after punctuation
          normalisation, 0 disagreed. This is the "vendor/broker instrument
          metadata" tier — a second venue's reference data for symbols NSE's own
          index files do not classify.

  Tier 4  'UNASSIGNED'.

NSE's per-symbol `/api/quote-equity` carries an `industryInfo` block that would
resolve every symbol at tier 1. It answers 403 to this client — with browser
headers, Chrome TLS impersonation, homepage warmup and a quote-page referer — so
it is not a source this system has. Nothing here silently substitutes for it.

─── Why the sector label is normalised ──────────────────────────────────────

§11.3 groups peers by matching `sector` strings. NSE writes
"Oil Gas & Consumable Fuels" and BSE writes "Oil, Gas & Consumable Fuels" for
the one sector, so copying both through raw would split a peer group in two and
silently starve it below SECTOR_MIN_PEERS. `normalise_sector` collapses both to
the NSE spelling before anything is stored.

    python -m app.ingest.symbol_master                  # fetch and load
    python -m app.ingest.symbol_master --from-cache-only
    python -m app.ingest.symbol_master --dry-run        # resolve, report, no write
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import sys
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.constants import (
    NSE_MAX_ATTEMPTS,
)
from app.constants import (
    VENDOR_CHECKPOINT_EVERY as _VENDOR_CHECKPOINT_EVERY,
)
from app.constants import (
    VENDOR_REQUEST_DELAY_S as _VENDOR_REQUEST_DELAY_S,
)
from app.constants import (
    VENDOR_TIMEOUT_S as _VENDOR_TIMEOUT_S,
)
from app.db import get_engine
from app.ingest import runs
from app.ingest.nse_client import (
    BROWSER_HEADERS,
    NSE_ARCHIVES,
    CacheMissError,
    NSEClient,
    NSEError,
    read_cached,
    sha256_bytes,
    write_cached,
)
from app.timeutil import IST

log = logging.getLogger(__name__)

# ─── Sources ────────────────────────────────────────────────────────────────
# Addresses, not thresholds, so they live here rather than in constants.py —
# the same rule `backend/scripts/backfill.py` follows.

SOURCE = "symbol_master"
CACHE_NAMESPACE = "reference"

EQUITY_LIST_FILE = "EQUITY_L.csv"
SYMBOL_CHANGE_FILE = "symbolchange.csv"
FO_LOTS_FILE = "fo_mktlots.csv"

# Tier 1. The broadest NSE-published file carrying the official Industry column.
PRIMARY_SECTOR_FILE = "ind_niftytotalmarket_list.csv"

# Tier 2. Broad-market and sectoral index constituent lists, in the order they
# are consulted. First answer wins, so a symbol in several lists takes the label
# from the earliest — they agree, but the order makes the outcome deterministic.
INDEX_CONSTITUENT_FILES = (
    "ind_nifty500list.csv",
    "ind_niftymicrocap250_list.csv",
    "ind_nifty50list.csv",
    "ind_niftynext50list.csv",
    "ind_nifty100list.csv",
    "ind_nifty200list.csv",
    "ind_niftymidcap150list.csv",
    "ind_niftysmallcap250list.csv",
    "ind_niftymidsmallcap400list.csv",
    "ind_niftylargemidcap250list.csv",
    "ind_niftybanklist.csv",
    "ind_niftyautolist.csv",
    "ind_niftyfinancelist.csv",
    "ind_niftyfmcglist.csv",
    "ind_niftyitlist.csv",
    "ind_niftymedialist.csv",
    "ind_niftymetallist.csv",
    "ind_niftypharmalist.csv",
    "ind_niftypsubanklist.csv",
    "ind_niftyrealtylist.csv",
    "ind_niftyhealthcarelist.csv",
    "ind_niftyconsumerdurableslist.csv",
    "ind_niftyoilgaslist.csv",
    "ind_niftycommoditieslist.csv",
    "ind_niftyconsumptionlist.csv",
    "ind_niftycpselist.csv",
    "ind_niftyenergylist.csv",
    "ind_niftyinfralist.csv",
    "ind_niftymnclist.csv",
    "ind_niftypselist.csv",
)

_EQUITIES_PATH = "content/equities"
_INDICES_PATH = "content/indices"
_FO_PATH = "content/fo"


def nse_reference_url(filename: str) -> str:
    """The archive URL a reference file is published at."""
    if filename.startswith("ind_"):
        return f"{NSE_ARCHIVES}/{_INDICES_PATH}/{filename}"
    if filename.startswith("fo_"):
        return f"{NSE_ARCHIVES}/{_FO_PATH}/{filename}"
    return f"{NSE_ARCHIVES}/{_EQUITIES_PATH}/{filename}"


# Tier 3 — the vendor. BSE's ListofScripData gives ISIN -> scrip code for the
# whole equity segment in one request; ComHeadernew gives that scrip's sector.
VENDOR = "BSE"
BSE_HOME = "https://www.bseindia.com"
BSE_API = "https://api.bseindia.com/BseIndiaAPI/api"
BSE_SCRIP_LIST_URL = (
    f"{BSE_API}/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status="
)
BSE_COMPANY_HEADER_URL = f"{BSE_API}/ComHeadernew/w?quotetype=EQ&scripcode={{code}}&seriesid="
VENDOR_SCRIP_LIST_CACHE = "bse_scrip_list.json"
VENDOR_SECTOR_CACHE = "bse_sector_by_isin.json"

# Transport mechanics — R1: sourced from the registry.
VENDOR_REQUEST_DELAY_S = _VENDOR_REQUEST_DELAY_S
VENDOR_TIMEOUT_S = _VENDOR_TIMEOUT_S
VENDOR_CHECKPOINT_EVERY = _VENDOR_CHECKPOINT_EVERY

# ─── Domain vocabulary ──────────────────────────────────────────────────────

# §2.1: NSE cash equities, EQ / BE / BZ series. Anything else in the file is out
# of scope and is quarantined rather than loaded.
IN_SCOPE_SERIES = ("EQ", "BE", "BZ")

UNASSIGNED = "UNASSIGNED"
PRIMARY_FILE = "PRIMARY_FILE"
INDEX_MAP = "INDEX_MAP"
VENDOR_SOURCE = "VENDOR"
# The `ck_instruments_sector_source` CHECK constraint, mirrored so the loader
# rejects an unknown tier before the database has to.
SECTOR_SOURCES = (PRIMARY_FILE, INDEX_MAP, VENDOR_SOURCE, UNASSIGNED)

# The 22 sector labels NSE's index files publish, after normalisation. Not a
# filter — a new sector is data, not an error — but an unrecognised label is
# logged, because it is more often a parse going wrong than NSE adding a sector.
KNOWN_SECTORS = frozenset(
    {
        "Automobile and Auto Components",
        "Capital Goods",
        "Chemicals",
        "Construction",
        "Construction Materials",
        "Consumer Durables",
        "Consumer Services",
        "Diversified",
        "Fast Moving Consumer Goods",
        "Financial Services",
        "Forest Materials",
        "Healthcare",
        "Information Technology",
        "Media Entertainment & Publication",
        "Metals & Mining",
        "Oil Gas & Consumable Fuels",
        "Power",
        "Realty",
        "Services",
        "Telecommunication",
        "Textiles",
        "Utilities",
    }
)

# NSE writes dates as 06-OCT-2008 in every reference file used here.
LISTING_DATE_FORMAT = "%d-%b-%Y"


class SymbolMasterError(RuntimeError):
    """A reference file could not be obtained or made sense of."""


# ─── Records ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InstrumentRow:
    """One EQUITY_L.csv row, parsed and in scope."""

    symbol: str
    name: str
    series: str
    isin: str | None
    face_value: Decimal | None
    listing_date: date | None


@dataclass(frozen=True)
class RejectedRow:
    """A row that will not be loaded. §6.2 rule 5 — quarantined, not dropped."""

    payload: dict[str, Any]
    reason: str


@dataclass(frozen=True)
class SectorResolution:
    sector: str
    sector_source: str


@dataclass(frozen=True)
class Alias:
    """One `symbol_aliases` row: a retired ticker and the instrument it became."""

    old_symbol: str
    symbol: str
    effective_date: date
    note: str


@dataclass
class LoadReport:
    """What a run did, in the shape the acceptance criteria are stated in."""

    as_of: date
    inputs_digest: str
    instruments: int = 0
    aliases: int = 0
    quarantined: int = 0
    deactivated: int = 0
    sector_source_counts: Counter[str] = field(default_factory=Counter)
    skipped_cached: bool = False

    @property
    def sector_coverage_ratio(self) -> float:
        """§19.2 `swl_sector_coverage_ratio` over the rows this run resolved.

        Every row it loads is active by construction, so this is the same
        quantity `sector_coverage_ratio(conn)` reads back from the database.
        """
        total = sum(self.sector_source_counts.values())
        if not total:
            return 0.0
        return (total - self.sector_source_counts[UNASSIGNED]) / total

    def log(self) -> None:
        log.info(
            "symbol master %s: %d instruments, %d aliases, %d quarantined, %d deactivated",
            self.as_of,
            self.instruments,
            self.aliases,
            self.quarantined,
            self.deactivated,
        )
        for source in SECTOR_SOURCES:
            count = self.sector_source_counts[source]
            share = count / max(self.instruments, 1)
            log.info("  sector_source %-13s %5d  %5.1f%%", source, count, 100 * share)
        log.info("  swl_sector_coverage_ratio %.4f", self.sector_coverage_ratio)


# ─── Parsing — pure functions over bytes ────────────────────────────────────


def _rows(payload: bytes) -> list[dict[str, str]]:
    """CSV rows, with header names and values stripped.

    NSE ships these files with a leading space on most column names
    (`SYMBOL,NAME OF COMPANY, SERIES, ...`) — the same quirk
    `docs/data-notes.md` records for the delivery file — and pads the F&O lot
    file to fixed width. utf-8-sig because several index files carry a BOM.
    """
    text = payload.decode("utf-8-sig", errors="strict")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise SymbolMasterError("file has no header row")
    reader.fieldnames = [name.strip() for name in reader.fieldnames]
    return [{k: (v or "").strip() for k, v in row.items() if k} for row in reader]


def _parse_nse_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, LISTING_DATE_FORMAT).date()
    except ValueError:
        return None


def _parse_decimal(raw: str) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def parse_equity_list(payload: bytes) -> tuple[list[InstrumentRow], list[RejectedRow]]:
    """EQUITY_L.csv -> instrument rows, plus the rows that cannot be loaded.

    A row is rejected, never repaired: a missing symbol or an out-of-scope
    series is a fact about the file, and §6.2 rule 5 wants the evidence kept.
    """
    instruments: list[InstrumentRow] = []
    rejected: list[RejectedRow] = []
    seen: set[str] = set()

    for row in _rows(payload):
        symbol = row.get("SYMBOL", "")
        series = row.get("SERIES", "")
        name = row.get("NAME OF COMPANY", "")
        if not symbol or not name or not series:
            rejected.append(RejectedRow(dict(row), "MISSING_REQUIRED_FIELD"))
            continue
        if series not in IN_SCOPE_SERIES:
            rejected.append(RejectedRow(dict(row), "SERIES_OUT_OF_SCOPE"))
            continue
        if symbol in seen:
            rejected.append(RejectedRow(dict(row), "DUPLICATE_SYMBOL"))
            continue

        listing_raw = row.get("DATE OF LISTING", "")
        listing_date = _parse_nse_date(listing_raw)
        if listing_raw and listing_date is None:
            rejected.append(RejectedRow(dict(row), "UNPARSED_LISTING_DATE"))
            continue

        seen.add(symbol)
        instruments.append(
            InstrumentRow(
                symbol=symbol,
                name=name,
                series=series,
                isin=row.get("ISIN NUMBER") or None,
                face_value=_parse_decimal(row.get("FACE VALUE", "")),
                listing_date=listing_date,
            )
        )
    return instruments, rejected


def normalise_sector(raw: str) -> str:
    """One spelling per sector, so §11.3 peer groups do not split.

    NSE and BSE differ only in commas and internal whitespace
    ("Oil, Gas & Consumable Fuels" vs "Oil Gas & Consumable Fuels"). The NSE
    spelling is canonical, because NSE is `primary_venue`.
    """
    return " ".join(raw.replace(",", " ").split())


def parse_index_constituents(payload: bytes) -> dict[str, str]:
    """An index constituent CSV -> {symbol: normalised sector}."""
    out: dict[str, str] = {}
    for row in _rows(payload):
        symbol = row.get("Symbol", "")
        industry = normalise_sector(row.get("Industry", ""))
        if symbol and industry:
            out.setdefault(symbol, industry)
    return out


def parse_fo_underlyings(payload: bytes) -> frozenset[str]:
    """fo_mktlots.csv -> the symbols with listed derivatives.

    Index underlyings (NIFTY, BANKNIFTY) fall out on their own by never matching
    an equity symbol, so no special case is needed for them.
    """
    return frozenset(row["SYMBOL"] for row in _rows(payload) if row.get("SYMBOL"))


def parse_symbol_changes(payload: bytes) -> list[tuple[str, str, str, date]]:
    """symbolchange.csv -> (company, old_symbol, new_symbol, effective_date).

    The file has no header: every line is a data row. A row whose date does not
    parse is skipped, because `symbol_aliases.effective_date` is NOT NULL and an
    invented date is worse than an absent alias.
    """
    text = payload.decode("utf-8-sig", errors="replace")
    changes: list[tuple[str, str, str, date]] = []
    for fields in csv.reader(io.StringIO(text)):
        if len(fields) < 4:
            continue
        company, old_symbol, new_symbol, raw_date = (f.strip() for f in fields[:4])
        effective = _parse_nse_date(raw_date)
        if not old_symbol or not new_symbol or effective is None:
            continue
        changes.append((company, old_symbol, new_symbol, effective))
    return changes


def build_aliases(
    changes: Sequence[tuple[str, str, str, date]], live_symbols: Iterable[str]
) -> list[Alias]:
    """Resolve rename chains onto currently listed instruments.

    Two things this has to get right, each of which otherwise produces a wrong
    historical join:

    Chains. `A -> B -> C` leaves a row saying `A -> B` even though B no longer
    exists. Each hop is followed until it lands on a live symbol, so A resolves
    to C. `effective_date` stays that of the first hop — the date A stopped
    being a valid ticker.

    Ticker reuse. §5.1 exists because exchanges reassign tickers. If a retired
    symbol is itself live again on a different instrument, an alias for it would
    make one ticker resolve two ways, so it is dropped and logged rather than
    guessed at.
    """
    live = set(live_symbols)
    forward = {old: new for _, old, new, _ in changes}
    aliases: list[Alias] = []
    reused: list[str] = []

    for company, old_symbol, new_symbol, effective in changes:
        if old_symbol in live:
            reused.append(old_symbol)
            continue
        current = new_symbol
        seen = {old_symbol}
        while current not in live and current in forward and current not in seen:
            seen.add(current)
            current = forward[current]
        if current not in live:
            continue
        aliases.append(
            Alias(
                old_symbol=old_symbol,
                symbol=current,
                effective_date=effective,
                note=f"{company}: {old_symbol} renamed to {new_symbol}",
            )
        )

    if reused:
        log.warning(
            "%d retired symbols are live again on another instrument and are not "
            "aliased (ticker reuse, §5.1): %s",
            len(reused),
            ", ".join(sorted(reused)[:10]),
        )
    # One row per old_symbol: the table is keyed on it. Later file rows win,
    # which is the most recent statement the exchange makes about that ticker.
    deduped = {alias.old_symbol: alias for alias in aliases}
    return sorted(deduped.values(), key=lambda alias: alias.old_symbol)


def resolve_sector(
    symbol: str,
    isin: str | None,
    primary: Mapping[str, str],
    index_map: Mapping[str, str],
    vendor: Mapping[str, str],
) -> SectorResolution:
    """The §5.1 fallback chain, in order. First answer wins."""
    sector = primary.get(symbol)
    if sector:
        return SectorResolution(sector, PRIMARY_FILE)
    sector = index_map.get(symbol)
    if sector:
        return SectorResolution(sector, INDEX_MAP)
    if isin:
        sector = vendor.get(isin)
        if sector:
            return SectorResolution(sector, VENDOR_SOURCE)
    return SectorResolution(UNASSIGNED, UNASSIGNED)


# ─── Fetching ───────────────────────────────────────────────────────────────


def snapshot_dir(cache_root: Path, as_of: date) -> Path:
    return Path(cache_root) / CACHE_NAMESPACE / as_of.isoformat()


def latest_cached_snapshot(cache_root: Path, not_after: date) -> date | None:
    """The most recent cached reference snapshot on or before `not_after`.

    Reference data is cached under the day it was fetched, so
    `--from-cache-only` has to look backwards rather than demand today's.
    """
    root = Path(cache_root) / CACHE_NAMESPACE
    if not root.is_dir():
        return None
    snapshots = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            snapshot = date.fromisoformat(child.name)
        except ValueError:
            continue
        if snapshot <= not_after:
            snapshots.append(snapshot)
    return max(snapshots) if snapshots else None


def fetch_nse_reference_files(client: NSEClient, as_of: date) -> dict[str, bytes]:
    """Every NSE reference file this module reads, through the §6.3 disk cache.

    A missing index file is a warning, not a failure: NSE renames and retires
    index files, tier 2 is a union, and losing one costs a handful of symbols
    that the coverage metric will show. A missing EQUITY_L.csv is fatal, because
    there is no symbol master without it.
    """
    payloads: dict[str, bytes] = {}
    required = (EQUITY_LIST_FILE,)
    wanted = (
        EQUITY_LIST_FILE,
        SYMBOL_CHANGE_FILE,
        FO_LOTS_FILE,
        PRIMARY_SECTOR_FILE,
        *INDEX_CONSTITUENT_FILES,
    )
    for filename in wanted:
        try:
            payload = client.fetch(
                nse_reference_url(filename),
                source=CACHE_NAMESPACE,
                target_date=as_of,
                filename=filename,
                endpoint="reference",
                accept_missing=True,
            )
        except (CacheMissError, NSEError) as exc:
            if filename in required:
                raise SymbolMasterError(f"{filename} is required: {exc}") from exc
            log.warning("reference file %s unavailable: %s", filename, exc)
            continue
        if payload is None:
            if filename in required:
                raise SymbolMasterError(f"{filename} is not published at its URL")
            log.warning("reference file %s is not published", filename)
            continue
        payloads[filename] = payload
    return payloads


class VendorSession:
    """A cookie-warmed BSE session, disk-cached like the NSE one.

    Deliberately small: this is reference metadata fetched once per snapshot,
    not a market-data path, so it borrows `nse_client`'s cache helpers and its
    §6.3 attempt cap and does without the circuit breaker.
    """

    def __init__(self, *, from_cache_only: bool = False) -> None:
        self.from_cache_only = from_cache_only
        self._session: Any = None
        self._last_request_at: float | None = None

    def __enter__(self) -> VendorSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session
        if self.from_cache_only:
            raise CacheMissError("--from-cache-only is set; no vendor session is opened")
        headers = {
            "User-Agent": BROWSER_HEADERS["User-Agent"],
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": BROWSER_HEADERS["Accept-Language"],
            "Referer": BSE_HOME + "/",
            "Origin": BSE_HOME,
        }
        try:
            from curl_cffi import requests as curl_requests

            session: Any = curl_requests.Session(
                headers=headers, timeout=VENDOR_TIMEOUT_S, impersonate="chrome"
            )
        except ImportError:
            import httpx

            session = httpx.Client(
                headers=headers, timeout=VENDOR_TIMEOUT_S, follow_redirects=True
            )
        # The API host only answers a session carrying the site's cookies.
        session.get(BSE_HOME + "/")
        self._session = session
        return session

    def _pace(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < VENDOR_REQUEST_DELAY_S:
                time.sleep(VENDOR_REQUEST_DELAY_S - elapsed)
        self._last_request_at = time.monotonic()

    def get_json(self, url: str) -> Any:
        session = self._ensure_session()
        last_error = "no attempt was made"
        for attempt in range(1, NSE_MAX_ATTEMPTS + 1):
            self._pace()
            try:
                response = session.get(url)
                if response.status_code == 200:
                    return json.loads(response.content)
                last_error = f"HTTP {response.status_code}"
            except Exception as exc:  # noqa: BLE001 — recorded, then retried
                last_error = f"{type(exc).__name__}: {exc}"
            log.debug(
                "vendor attempt %d/%d for %s: %s", attempt, NSE_MAX_ATTEMPTS, url, last_error
            )
            time.sleep(VENDOR_REQUEST_DELAY_S * attempt)
        raise SymbolMasterError(f"{url} failed after {NSE_MAX_ATTEMPTS} attempts: {last_error}")


def fetch_vendor_sectors(
    isins: Sequence[str],
    *,
    as_of: date,
    cache_root: Path,
    from_cache_only: bool = False,
) -> dict[str, str]:
    """{ISIN: normalised sector} from the vendor, for the ISINs given.

    Cached as one JSON document per snapshot and checkpointed as it goes, so an
    interrupted run resumes rather than re-asking for what it already knows.
    Only the ISINs the NSE tiers left unresolved are ever requested.

    The vendor's answer is discarded unless the ISIN it echoes back is the one
    asked for. A scrip-code mapping that had drifted would otherwise attach one
    company's sector to another's symbol — plausible, wrong, and invisible.
    """
    cache_file = snapshot_dir(cache_root, as_of) / VENDOR_SECTOR_CACHE
    resolved: dict[str, str] = {}
    cached = read_cached(cache_file)
    if cached is not None:
        resolved = {k: v for k, v in json.loads(cached).items() if isinstance(v, str)}

    missing = [isin for isin in isins if isin not in resolved]
    if not missing:
        return resolved
    if from_cache_only:
        log.warning(
            "--from-cache-only: %d ISINs have no cached vendor sector and stay UNASSIGNED",
            len(missing),
        )
        return resolved

    def checkpoint() -> None:
        write_cached(cache_file, json.dumps(resolved, sort_keys=True).encode("utf-8"))

    with VendorSession(from_cache_only=from_cache_only) as session:
        listing_file = snapshot_dir(cache_root, as_of) / VENDOR_SCRIP_LIST_CACHE
        listing_raw = read_cached(listing_file)
        if listing_raw is None:
            listing = session.get_json(BSE_SCRIP_LIST_URL)
            write_cached(listing_file, json.dumps(listing).encode("utf-8"))
        else:
            listing = json.loads(listing_raw)

        codes: dict[str, str] = {}
        for row in listing:
            isin = str(row.get("ISIN_NUMBER") or "").strip()
            code = str(row.get("SCRIP_CD") or "").strip()
            if isin and code:
                codes.setdefault(isin, code)

        askable = [isin for isin in missing if isin in codes]
        log.info(
            "vendor lookup: %d of %d unresolved ISINs are listed by %s (of %d %s ISINs)",
            len(askable),
            len(missing),
            VENDOR,
            len(codes),
            VENDOR,
        )
        for done, isin in enumerate(askable, start=1):
            try:
                header = session.get_json(BSE_COMPANY_HEADER_URL.format(code=codes[isin]))
            except SymbolMasterError as exc:
                log.warning("vendor lookup for %s failed: %s", isin, exc)
                continue
            echoed = str(header.get("ISIN") or "").strip()
            if echoed != isin:
                log.warning(
                    "vendor returned ISIN %s for %s; discarded rather than attaching "
                    "another company's sector",
                    echoed or "<none>",
                    isin,
                )
                continue
            sector = normalise_sector(str(header.get("IndustryNew") or ""))
            if sector:
                resolved[isin] = sector
            if done % VENDOR_CHECKPOINT_EVERY == 0:
                checkpoint()
                log.info("vendor lookup %d/%d", done, len(askable))
    checkpoint()
    return resolved


def inputs_digest(payloads: Mapping[str, bytes]) -> str:
    """One SHA-256 over every reference input, for §6.2 rule 3.

    Rule 3 hashes the downloaded file and skips parsing when it matches a prior
    successful run for the same source and date. This run reads many files, and
    a sector can change because an index file changed while EQUITY_L.csv did
    not, so the hash covers all of them together — hashing only the equity list
    would skip a run that had real work to do.
    """
    digest = hashlib.sha256()
    for name in sorted(payloads):
        digest.update(name.encode("utf-8"))
        digest.update(sha256_bytes(payloads[name]).encode("ascii"))
    return digest.hexdigest()


# ─── Loading ────────────────────────────────────────────────────────────────

_UPSERT_INSTRUMENT = sa.text(
    """
    INSERT INTO instruments (
        symbol, isin, name, series, sector, sector_source, face_value,
        listing_date, is_active, primary_venue, has_derivatives
    ) VALUES (
        :symbol, :isin, :name, :series, :sector, :sector_source, :face_value,
        :listing_date, TRUE, 'NSE', :has_derivatives
    )
    ON CONFLICT (symbol) DO UPDATE SET
        isin            = EXCLUDED.isin,
        name            = EXCLUDED.name,
        series          = EXCLUDED.series,
        sector          = EXCLUDED.sector,
        sector_source   = EXCLUDED.sector_source,
        face_value      = EXCLUDED.face_value,
        listing_date    = EXCLUDED.listing_date,
        is_active       = TRUE,
        has_derivatives = EXCLUDED.has_derivatives
    """
)

# instrument_id is looked up rather than passed in: it is the BIGSERIAL surrogate
# and only the database knows it. A rename whose target is absent inserts nothing.
_UPSERT_ALIAS = sa.text(
    """
    INSERT INTO symbol_aliases (old_symbol, instrument_id, effective_date, note)
    SELECT :old_symbol, i.instrument_id, :effective_date, :note
    FROM instruments i WHERE i.symbol = :symbol
    ON CONFLICT (old_symbol) DO UPDATE SET
        instrument_id  = EXCLUDED.instrument_id,
        effective_date = EXCLUDED.effective_date,
        note           = EXCLUDED.note
    """
)


def sector_coverage_ratio(conn: sa.Connection) -> float:
    """§19.2 `swl_sector_coverage_ratio`, read back from the database.

    Active symbols only: an unassigned sector on a delisted instrument costs
    nothing, because §11.3 only ever groups peers that have a bar on the day.
    """
    total, resolved = conn.execute(
        sa.text(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE sector <> :unassigned) "
            "FROM instruments WHERE is_active"
        ),
        {"unassigned": UNASSIGNED},
    ).one()
    return (resolved / total) if total else 0.0


def sector_source_distribution(conn: sa.Connection) -> Counter[str]:
    """The §1.1 acceptance artefact: how many symbols each tier resolved."""
    rows = conn.execute(
        sa.text(
            "SELECT sector_source, COUNT(*) FROM instruments WHERE is_active "
            "GROUP BY sector_source"
        )
    ).all()
    return Counter({str(source): int(count) for source, count in rows})


def resolve(
    payloads: Mapping[str, bytes], vendor: Mapping[str, str]
) -> tuple[
    list[InstrumentRow],
    list[RejectedRow],
    dict[str, SectorResolution],
    list[Alias],
    frozenset[str],
]:
    """Everything between the bytes and the database, with no I/O of its own."""
    instruments, rejected = parse_equity_list(payloads[EQUITY_LIST_FILE])
    if not instruments:
        raise SymbolMasterError("EQUITY_L.csv parsed to zero in-scope instruments")

    primary: dict[str, str] = {}
    if PRIMARY_SECTOR_FILE in payloads:
        primary = parse_index_constituents(payloads[PRIMARY_SECTOR_FILE])
    index_map: dict[str, str] = {}
    for filename in INDEX_CONSTITUENT_FILES:
        if filename in payloads:
            for symbol, sector in parse_index_constituents(payloads[filename]).items():
                index_map.setdefault(symbol, sector)

    resolutions = {
        row.symbol: resolve_sector(row.symbol, row.isin, primary, index_map, vendor)
        for row in instruments
    }
    unknown = {r.sector for r in resolutions.values()} - KNOWN_SECTORS - {UNASSIGNED}
    if unknown:
        log.warning("sector labels outside the published NSE set: %s", sorted(unknown))

    aliases: list[Alias] = []
    if SYMBOL_CHANGE_FILE in payloads:
        aliases = build_aliases(
            parse_symbol_changes(payloads[SYMBOL_CHANGE_FILE]),
            (row.symbol for row in instruments),
        )

    fo_underlyings: frozenset[str] = frozenset()
    if FO_LOTS_FILE in payloads:
        fo_underlyings = parse_fo_underlyings(payloads[FO_LOTS_FILE])

    return instruments, rejected, resolutions, aliases, fo_underlyings


def unresolved_isins(
    instruments: Sequence[InstrumentRow], payloads: Mapping[str, bytes]
) -> list[str]:
    """The ISINs the two NSE tiers cannot resolve — the vendor's whole workload."""
    primary: dict[str, str] = {}
    if PRIMARY_SECTOR_FILE in payloads:
        primary = parse_index_constituents(payloads[PRIMARY_SECTOR_FILE])
    index_map: dict[str, str] = {}
    for filename in INDEX_CONSTITUENT_FILES:
        if filename in payloads:
            index_map.update(parse_index_constituents(payloads[filename]))
    return [
        row.isin
        for row in instruments
        if row.isin and row.symbol not in primary and row.symbol not in index_map
    ]


def load(
    *,
    as_of: date,
    from_cache_only: bool = False,
    cache_root: Path | None = None,
    use_vendor: bool = True,
    dry_run: bool = False,
    engine: sa.Engine | None = None,
) -> LoadReport:
    """Fetch, resolve, and write the symbol master. One transaction (§6.2 rule 7)."""
    from app.config import get_settings

    cache_root = Path(cache_root or get_settings().cache_root)
    snapshot = as_of
    if from_cache_only:
        found = latest_cached_snapshot(cache_root, as_of)
        if found is None:
            raise SymbolMasterError(
                "--from-cache-only and no cached reference snapshot under "
                f"{cache_root / CACHE_NAMESPACE}"
            )
        snapshot = found
        log.info("reading the cached reference snapshot of %s", snapshot)

    with NSEClient(from_cache_only=from_cache_only, cache_root=cache_root) as client:
        payloads = fetch_nse_reference_files(client, snapshot)

    vendor: dict[str, str] = {}
    if use_vendor:
        instruments, _ = parse_equity_list(payloads[EQUITY_LIST_FILE])
        vendor = fetch_vendor_sectors(
            unresolved_isins(instruments, payloads),
            as_of=snapshot,
            cache_root=cache_root,
            from_cache_only=from_cache_only,
        )

    instruments, rejected, resolutions, aliases, fo_underlyings = resolve(payloads, vendor)

    digest = inputs_digest(payloads)
    report = LoadReport(as_of=snapshot, inputs_digest=digest)
    report.instruments = len(instruments)
    report.aliases = len(aliases)
    report.quarantined = len(rejected)
    report.sector_source_counts = Counter(r.sector_source for r in resolutions.values())

    if dry_run:
        log.info("--dry-run: nothing written")
        report.log()
        return report

    engine = engine or get_engine()
    with engine.begin() as conn:
        if runs.already_ingested(conn, source=SOURCE, target_date=snapshot, file_hash=digest):
            log.info("reference inputs unchanged since the last successful run (§6.2 rule 3)")
            runs.finish_run(
                conn,
                runs.start_run(conn, source=SOURCE, target_date=snapshot, file_hash=digest),
                status="SKIPPED_CACHED",
                rows=len(instruments),
            )
            report.skipped_cached = True
            report.log()
            return report

        run_id = runs.start_run(conn, source=SOURCE, target_date=snapshot, file_hash=digest)
        conn.execute(
            _UPSERT_INSTRUMENT,
            [
                {
                    "symbol": row.symbol,
                    "isin": row.isin,
                    "name": row.name,
                    "series": row.series,
                    "sector": resolutions[row.symbol].sector,
                    "sector_source": resolutions[row.symbol].sector_source,
                    "face_value": row.face_value,
                    "listing_date": row.listing_date,
                    "has_derivatives": row.symbol in fo_underlyings,
                }
                for row in instruments
            ],
        )
        # Delisted, not deleted: fact tables key on `symbol`, so history has to
        # keep resolving. §6.2's active-row floor counts only is_active rows.
        report.deactivated = conn.execute(
            sa.text(
                "UPDATE instruments SET is_active = FALSE "
                "WHERE is_active AND NOT (symbol = ANY(:symbols))"
            ),
            {"symbols": [row.symbol for row in instruments]},
        ).rowcount
        if aliases:
            conn.execute(
                _UPSERT_ALIAS,
                [
                    {
                        "old_symbol": alias.old_symbol,
                        "symbol": alias.symbol,
                        "effective_date": alias.effective_date,
                        "note": alias.note,
                    }
                    for alias in aliases
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
                        "source_file": EQUITY_LIST_FILE,
                        "payload": json.dumps(row.payload, sort_keys=True),
                        "reason": row.reason,
                    }
                    for row in rejected
                ],
            )
        runs.finish_run(conn, run_id, status="OK", rows=len(instruments))

    with engine.connect() as conn:
        measured = sector_coverage_ratio(conn)
    report.log()
    log.info("  swl_sector_coverage_ratio (active, read back) %.4f", measured)
    return report


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the symbol master (§5.1).")
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="Snapshot date for the reference cache. Default: today in IST.",
    )
    parser.add_argument(
        "--from-cache-only",
        action="store_true",
        help="Never touch the network; read the newest cached snapshot.",
    )
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument(
        "--no-vendor",
        action="store_true",
        help="Skip the tier-3 vendor lookup. Lowers coverage; useful offline.",
    )
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
            from_cache_only=args.from_cache_only,
            cache_root=args.cache_root,
            use_vendor=not args.no_vendor,
            dry_run=args.dry_run,
        )
    except SymbolMasterError as exc:
        log.error("symbol master failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
