"""09:30 index snapshot capture and Rule R2 backfill."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa

from app.db import get_engine
from app.timeutil import IST

PRIMARY_INDEXES = ("Nifty 50", "Nifty Total Market")
LIVE_0930 = "LIVE_0930"
BROKER_1M = "BROKER_1M"
ESTIMATED_FROM_OPEN = "ESTIMATED_FROM_OPEN"

_QUALITY_PRIORITY = {ESTIMATED_FROM_OPEN: 1, BROKER_1M: 2, LIVE_0930: 3}
_SOURCE_BY_QUALITY = {
    LIVE_0930: "CAPTURED_LIVE",
    BROKER_1M: "BROKER_CANDLE",
    ESTIMATED_FROM_OPEN: "ESTIMATED_FROM_OPEN",
}
ValueProvider = Callable[[str, date], Decimal | int | float | None]
Provider = Mapping[tuple[str, date], Decimal | int | float | None] | ValueProvider | None


def _value(provider: Provider, index_symbol: str, trading_date: date) -> Decimal | None:
    if provider is None:
        return None
    raw: Decimal | int | float | None
    if callable(provider):
        raw = provider(index_symbol, trading_date)
    else:
        raw = provider.get((index_symbol, trading_date))
    return None if raw is None else Decimal(str(raw))


def _open_values(
    conn: sa.Connection, index_symbol: str, trading_date: date
) -> Decimal | None:
    value = conn.execute(
        sa.text(
            "SELECT open FROM index_bars "
            "WHERE index_symbol = :index_symbol AND date = :trading_date"
        ),
        {"index_symbol": index_symbol, "trading_date": trading_date},
    ).scalar_one_or_none()
    return None if value is None else Decimal(str(value))


def upsert_index_snapshot(
    index_symbol: str,
    trading_date: date,
    value: Decimal | int | float,
    quality_flag: str,
    *,
    engine: sa.Engine | None = None,
    captured_at: datetime | None = None,
    ingested_at: datetime | None = None,
) -> bool:
    """Insert or upgrade one snapshot; lower quality can never overwrite higher quality."""
    if quality_flag not in _QUALITY_PRIORITY:
        raise ValueError(f"unsupported 09:30 quality flag: {quality_flag}")
    engine = engine or get_engine()
    captured_at = captured_at or datetime.now(IST)
    ingested_at = ingested_at or datetime.now(IST)
    result = None
    with engine.begin() as conn:
        result = conn.execute(
            sa.text(
                "INSERT INTO index_snapshots_0930 "
                "(index_symbol, trading_date, value, captured_at, source, "
                "quality_flag, ingested_at) "
                "VALUES (:index_symbol, :trading_date, :value, :captured_at, :source, "
                ":quality_flag, :ingested_at) "
                "ON CONFLICT (index_symbol, trading_date) DO UPDATE SET "
                "value = EXCLUDED.value, captured_at = EXCLUDED.captured_at, "
                "source = EXCLUDED.source, quality_flag = EXCLUDED.quality_flag, "
                "ingested_at = EXCLUDED.ingested_at "
                "WHERE CASE index_snapshots_0930.quality_flag "
                "WHEN 'LIVE_0930' THEN 3 WHEN 'BROKER_1M' THEN 2 "
                "WHEN 'ESTIMATED_FROM_OPEN' THEN 1 ELSE 0 END "
                "< CASE EXCLUDED.quality_flag "
                "WHEN 'LIVE_0930' THEN 3 WHEN 'BROKER_1M' THEN 2 "
                "WHEN 'ESTIMATED_FROM_OPEN' THEN 1 ELSE 0 END"
            ),
            {
                "index_symbol": index_symbol,
                "trading_date": trading_date,
                "value": Decimal(str(value)),
                "captured_at": captured_at,
                "source": _SOURCE_BY_QUALITY[quality_flag],
                "quality_flag": quality_flag,
                "ingested_at": ingested_at,
            },
        )
    return bool(result.rowcount)


def capture_index_snapshot_0930(
    trading_date: date,
    *,
    live_provider: Provider = None,
    broker_provider: Provider = None,
    engine: sa.Engine | None = None,
    indexes: Iterable[str] = PRIMARY_INDEXES,
    captured_at: datetime | None = None,
) -> dict[str, str]:
    """Capture the best available value for each benchmark on one trading date."""
    engine = engine or get_engine()
    captured: dict[str, str] = {}
    with engine.begin() as conn:
        for index_symbol in indexes:
            value = _value(live_provider, index_symbol, trading_date)
            quality = LIVE_0930
            if value is None:
                value = _value(broker_provider, index_symbol, trading_date)
                quality = BROKER_1M
            if value is None:
                value = _open_values(conn, index_symbol, trading_date)
                quality = ESTIMATED_FROM_OPEN
            if value is None:
                raise LookupError(
                    f"no 09:30 snapshot source for {index_symbol} on {trading_date}"
                )
            conn.execute(
                sa.text(
                    "INSERT INTO index_snapshots_0930 "
                    "(index_symbol, trading_date, value, captured_at, source, "
                    "quality_flag, ingested_at) "
                    "VALUES (:index_symbol, :trading_date, :value, :captured_at, :source, "
                    ":quality_flag, :ingested_at) "
                    "ON CONFLICT (index_symbol, trading_date) DO UPDATE SET "
                    "value = EXCLUDED.value, captured_at = EXCLUDED.captured_at, "
                    "source = EXCLUDED.source, quality_flag = EXCLUDED.quality_flag, "
                    "ingested_at = EXCLUDED.ingested_at "
                    "WHERE CASE index_snapshots_0930.quality_flag "
                    "WHEN 'LIVE_0930' THEN 3 WHEN 'BROKER_1M' THEN 2 "
                    "WHEN 'ESTIMATED_FROM_OPEN' THEN 1 ELSE 0 END "
                    "< CASE EXCLUDED.quality_flag "
                    "WHEN 'LIVE_0930' THEN 3 WHEN 'BROKER_1M' THEN 2 "
                    "WHEN 'ESTIMATED_FROM_OPEN' THEN 1 ELSE 0 END"
                ),
                {
                    "index_symbol": index_symbol,
                    "trading_date": trading_date,
                    "value": value,
                    "captured_at": captured_at or datetime.now(IST),
                    "source": _SOURCE_BY_QUALITY[quality],
                    "quality_flag": quality,
                    "ingested_at": datetime.now(IST),
                },
            )
            captured[index_symbol] = quality
    return captured


def backfill_index_snapshots_0930(
    trading_dates: Iterable[date],
    *,
    live_provider: Provider = None,
    broker_provider: Provider = None,
    engine: sa.Engine | None = None,
    indexes: Iterable[str] = PRIMARY_INDEXES,
) -> int:
    """Backfill every requested trading date and fail rather than leave a gap."""
    index_list = tuple(indexes)
    count = 0
    for trading_date in trading_dates:
        capture_index_snapshot_0930(
            trading_date,
            live_provider=live_provider,
            broker_provider=broker_provider,
            engine=engine,
            indexes=index_list,
        )
        count += len(index_list)
    return count


def estimated_from_open_count(conn: sa.Connection) -> int:
    return int(
        conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM index_snapshots_0930 "
                "WHERE quality_flag = 'ESTIMATED_FROM_OPEN'"
            )
        ).scalar_one()
    )
