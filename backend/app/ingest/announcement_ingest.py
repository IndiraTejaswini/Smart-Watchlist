"""NSE corporate-announcement polling and historical backfill."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from app.config import get_settings
from app.db import get_engine
from app.ingest.announcements import resolve_category
from app.ingest.nse_client import CircuitOpenError, NSEClient

log = logging.getLogger(__name__)
SOURCE = "announcements"
ANNOUNCEMENT_URL = "https://www.nseindia.com/api/corporate-announcements"
ANNOUNCEMENT_POLL_SECONDS = 180


@dataclass(frozen=True)
class Announcement:
    symbol: str
    filed_at: datetime
    subject: str
    category: str
    para_ref: str | None
    attachment_url: str | None
    raw_json: dict[str, Any]
    content_hash: str

    @property
    def headline(self) -> str:
        return self.subject

    @property
    def body_text(self) -> str:
        value = self.raw_json.get("body_text", self.raw_json.get("body", ""))
        return "" if value is None else str(value)


def _text(raw: Any) -> str:
    return "" if raw is None else str(raw).strip()


def _filed_at(raw: Any) -> datetime:
    value = _text(raw)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError("announcement filed_at must be timezone-aware")
    return parsed


def content_hash(symbol: str, subject: str, filed_at: datetime) -> str:
    normalized = "\x1f".join(
        (_text(symbol).upper(), " ".join(_text(subject).split()), filed_at.isoformat())
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_announcements(payload: bytes | str | dict[str, Any] | list[Any]) -> list[Announcement]:
    if isinstance(payload, bytes):
        decoded: Any = json.loads(payload)
    elif isinstance(payload, str):
        decoded = json.loads(payload)
    else:
        decoded = payload
    items = decoded.get("data", decoded) if isinstance(decoded, dict) else decoded
    if not isinstance(items, list):
        raise ValueError("announcement payload must contain a list")

    parsed: list[Announcement] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("announcement item must be an object")
        symbol = _text(item.get("symbol") or item.get("symbolName"))
        subject = _text(item.get("subject") or item.get("desc"))
        filed_at = _filed_at(item.get("filed_at") or item.get("dt") or item.get("date"))
        resolution = resolve_category(desc=_text(item.get("desc")), subject=subject)
        parsed.append(
            Announcement(
                symbol=symbol,
                filed_at=filed_at,
                subject=subject,
                category=resolution.category,
                para_ref=_text(item.get("para_ref") or item.get("paraRef")) or None,
                attachment_url=(
                    _text(item.get("attachment_url") or item.get("attchmntFile")) or None
                ),
                raw_json=item,
                content_hash=content_hash(symbol, subject, filed_at),
            )
        )
    return parsed


def ingest_announcements(
    announcements: list[Announcement],
    *,
    engine: sa.Engine | None = None,
) -> int:
    """Insert announcements atomically and return the number newly inserted."""
    engine = engine or get_engine()
    if not announcements:
        return 0
    with engine.begin() as conn:
        result = conn.execute(
            sa.text(
                "INSERT INTO announcements "
                "(symbol, filed_at, subject, category, para_ref, attachment_url, "
                "raw_json, content_hash, source, ingested_at) "
                "VALUES (:symbol, :filed_at, :subject, :category, :para_ref, "
                ":attachment_url, CAST(:raw_json AS jsonb), :content_hash, "
                ":source, CURRENT_TIMESTAMP) "
                "ON CONFLICT (content_hash) DO NOTHING"
            ),
            [
                {
                    "symbol": item.symbol,
                    "filed_at": item.filed_at,
                    "subject": item.subject,
                    "category": item.category,
                    "para_ref": item.para_ref,
                    "attachment_url": item.attachment_url,
                    "raw_json": json.dumps(item.raw_json),
                    "content_hash": item.content_hash,
                    "source": SOURCE,
                }
                for item in announcements
            ],
        )
    return int(result.rowcount)


def poll_once(
    *,
    engine: sa.Engine | None = None,
    client: NSEClient | None = None,
    page: int = 0,
    from_cache_only: bool = False,
) -> int:
    engine = engine or get_engine()
    own_client = client is None
    client = client or NSEClient(
        from_cache_only=from_cache_only, cache_root=get_settings().cache_root
    )
    try:
        today = date.today()
        payload = client.fetch(
            f"{ANNOUNCEMENT_URL}?page={page}",
            source=SOURCE,
            target_date=today,
            filename=f"page-{page}.json",
            endpoint=SOURCE,
        )
        if payload is None:
            return 0
        return ingest_announcements(parse_announcements(payload), engine=engine)
    except CircuitOpenError:
        log.warning("announcement poll deferred while NSE breaker is open")
        return 0
    finally:
        if own_client:
            client.close()


def backfill(
    start: date,
    end: date,
    *,
    engine: sa.Engine | None = None,
    client: NSEClient | None = None,
    chunk_days: int = 7,
) -> int:
    """Fetch historical announcement pages in bounded date chunks."""
    if end < start:
        raise ValueError("backfill end must not precede start")
    inserted = 0
    cursor = start
    page = 0
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days - 1))
        own_client = client is None
        active_client = client or NSEClient(cache_root=get_settings().cache_root)
        try:
            payload = active_client.fetch(
                f"{ANNOUNCEMENT_URL}?from={cursor:%d-%m-%Y}&to={chunk_end:%d-%m-%Y}&page={page}",
                source=SOURCE,
                target_date=cursor,
                filename=f"{cursor.isoformat()}-{chunk_end.isoformat()}-{page}.json",
                endpoint=SOURCE,
            )
            if payload:
                inserted += ingest_announcements(parse_announcements(payload), engine=engine)
        except CircuitOpenError:
            log.warning("announcement backfill paused by NSE breaker")
            time.sleep(float(active_client.breaker.snapshot()["cooldown_remaining_s"] or 0))
        finally:
            if own_client:
                active_client.close()
        cursor = chunk_end + timedelta(days=1)
        page += 1
    return inserted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill NSE corporate announcements.")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    print(backfill(args.start, args.end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
