"""12-month EOD backfill of bhavcopy + delivery files — BUILD_PLAN task 0.1.

Downloads only. Parsing, validation, quarantine and the database write path are
Phase 2 (`ingest/bhavcopy.py`, `ingest/delivery.py`); this exists so the files
are on local disk before anything else needs them, because the network is the
least reliable component in the system and the one most likely to burn
irreplaceable hours.

Every file lands at data/cache/{source}/{date}/{filename} with a SHA-256
sidecar, written by `app.ingest.nse_client`. Re-running is free: a cached file
with a matching digest never touches the network.

    python backend/scripts/backfill.py                 # last 12 months
    python backend/scripts/backfill.py --months 3
    python backend/scripts/backfill.py --from-cache-only   # verify, no network

A ledger at data/cache/backfill_state.json records the outcome per source and
date, so an interrupted run resumes where it stopped and settled holidays are
not re-requested. A date that returned 404 is retried only if it is recent
enough that the file may simply not have been published yet.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ingest.nse_client import (  # noqa: E402
    NSE_ARCHIVES,
    CacheMissError,
    CircuitOpenError,
    NSEClient,
    NSEError,
    cache_path,
    read_cached,
    sidecar_path,
)

log = logging.getLogger("backfill")

# NSE publishes both files under nsearchives. Named here rather than in
# constants.py because they are addresses, not thresholds.
BHAVCOPY_SOURCE = "bhavcopy"
DELIVERY_SOURCE = "delivery"

STATE_FILE = Path("data/cache/backfill_state.json")

# A 404 on a date this recent may just mean "not published yet", so it is
# retried on the next run. Older 404s are settled holidays.
RECENT_RETRY_DAYS = 7

DAYS_PER_MONTH = 30  # calendar arithmetic for the --months window, not a threshold


def bhavcopy_url(d: date) -> tuple[str, str]:
    """UDiFF common bhavcopy — OHLC, prev close, volume, turnover, trades, series."""
    filename = f"BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    return f"{NSE_ARCHIVES}/content/cm/{filename}", filename


def delivery_url(d: date) -> tuple[str, str]:
    """Security-wise deliverable positions — deliverable quantity and delivery %."""
    filename = f"sec_bhavdata_full_{d:%d%m%Y}.csv"
    return f"{NSE_ARCHIVES}/products/content/{filename}", filename


SOURCES = {
    BHAVCOPY_SOURCE: bhavcopy_url,
    DELIVERY_SOURCE: delivery_url,
}


def delivery_content_date(payload: bytes) -> date | None:
    """The trading date the delivery file's rows actually carry (its DATE1).

    Why this check exists. On an exchange holiday the bhavcopy URL returns 404,
    but the delivery URL returns HTTP 200 carrying the PREVIOUS trading day's
    rows. Verified empirically over a 12-month backfill: of 174 files, the 163
    trading days matched their requested date and all 11 mismatches were
    holidays, each off by exactly one trading session.

    Caching such a file under the requested date would hand Phase 2 a file whose
    name says one date and whose contents say another — the exact silent
    wrongness R3 and R5 exist to prevent. It would double-count one session in
    the 20-day delivery baseline and invent activity on a day the market was
    shut.

    This reads one row to establish identity. It is not parsing or validation —
    that is Phase 2 (`ingest/delivery.py`), and it stays there.
    """
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
        first = next(reader)
    except StopIteration:
        return None
    try:
        column = [h.strip().upper() for h in header].index("DATE1")
        return datetime.strptime(first[column].strip(), "%d-%b-%Y").date()
    except (ValueError, IndexError):
        return None


def quarantine_stale(path: Path, requested: date, cache_root: Path) -> Path:
    """Move a file whose contents belong to another date out of the dated dir.

    Moved, never deleted — §6.2 quarantines rejected data rather than dropping
    it, so the evidence survives for inspection.
    """
    destination = cache_root / f"{DELIVERY_SOURCE}_stale" / requested.isoformat()
    destination.mkdir(parents=True, exist_ok=True)
    for src in (path, sidecar_path(path)):
        if src.exists():
            src.replace(destination / src.name)
    try:
        path.parent.rmdir()
    except OSError:
        pass
    return destination


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("backfill ledger at %s is unreadable, starting a fresh one", path)
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def weekdays(start: date, end: date):
    """Every Mon-Fri from start to end inclusive.

    Weekends are skipped because NSE never publishes on them. Exchange holidays
    are not known yet — the trading calendar is Phase 1.2 — so they are left to
    return 404 and be recorded as MISSING.
    """
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def run(
    *,
    months: int,
    from_cache_only: bool,
    cache_root: Path,
    state_file: Path,
    sources: list[str],
) -> int:
    end = date.today()
    start = end - timedelta(days=months * DAYS_PER_MONTH)
    state = load_state(state_file)
    counts = {"cached": 0, "downloaded": 0, "missing": 0, "stale": 0, "failed": 0}

    log.info(
        "backfill %s to %s, sources=%s, from_cache_only=%s",
        start,
        end,
        ",".join(sources),
        from_cache_only,
    )

    with NSEClient(from_cache_only=from_cache_only, cache_root=cache_root) as client:
        for d in weekdays(start, end):
            for source in sources:
                url, filename = SOURCES[source](d)
                key = f"{source}/{d.isoformat()}"
                prior = state.get(key, {}).get("status")
                path = cache_path(source, d, filename, cache_root)

                if prior == "OK" and read_cached(path) is not None:
                    counts["cached"] += 1
                    continue
                if prior == "MISSING" and (end - d).days > RECENT_RETRY_DAYS:
                    counts["missing"] += 1
                    continue
                if prior == "STALE_CONTENT" and (end - d).days > RECENT_RETRY_DAYS:
                    counts["stale"] += 1
                    continue

                try:
                    payload = client.fetch(
                        url,
                        source=source,
                        target_date=d,
                        filename=filename,
                        endpoint=source,
                        accept_missing=True,
                    )
                except CacheMissError:
                    counts["missing"] += 1
                    continue
                except CircuitOpenError as exc:
                    log.error("stopping: %s", exc)
                    save_state(state_file, state)
                    return 1
                except NSEError as exc:
                    counts["failed"] += 1
                    state[key] = {"status": "FAILED", "error": str(exc)}
                    log.error("%s %s failed: %s", source, d, exc)
                    save_state(state_file, state)
                    continue

                if payload is None:
                    counts["missing"] += 1
                    state[key] = {"status": "MISSING", "url": url}
                    save_state(state_file, state)
                    continue

                if source == DELIVERY_SOURCE:
                    content = delivery_content_date(payload)
                    if content is not None and content != d:
                        counts["stale"] += 1
                        moved = quarantine_stale(path, d, cache_root)
                        state[key] = {
                            "status": "STALE_CONTENT",
                            "url": url,
                            "content_date": content.isoformat(),
                            "quarantined_to": str(moved),
                        }
                        log.warning(
                            "%s %s served %s instead — not a trading day. "
                            "Quarantined to %s",
                            source,
                            d,
                            content,
                            moved,
                        )
                        save_state(state_file, state)
                        continue

                counts["downloaded"] += 1
                state[key] = {
                    "status": "OK",
                    "url": url,
                    "bytes": len(payload),
                    "path": str(path),
                }
                log.info("%s %s ok, %d bytes", source, d, len(payload))
                save_state(state_file, state)

    save_state(state_file, state)
    log.info(
        "backfill finished: %d downloaded, %d already cached, %d not published, "
        "%d stale-content quarantined, %d failed "
        "(transport=%s, cache hit ratio %.2f)",
        counts["downloaded"],
        counts["cached"],
        counts["missing"],
        counts["stale"],
        counts["failed"],
        client.transport,
        client.metrics.cache_hit_ratio,
    )
    return 1 if counts["failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument(
        "--from-cache-only",
        action="store_true",
        help="Never touch the network; read only what is already on disk.",
    )
    parser.add_argument("--cache-root", type=Path, default=Path("data/cache"))
    parser.add_argument("--state-file", type=Path, default=STATE_FILE)
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(SOURCES),
        help="Restrict to one source. Repeatable. Default: all.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    return run(
        months=args.months,
        from_cache_only=args.from_cache_only,
        cache_root=args.cache_root,
        state_file=args.state_file,
        sources=args.source or sorted(SOURCES),
    )


if __name__ == "__main__":
    raise SystemExit(main())
