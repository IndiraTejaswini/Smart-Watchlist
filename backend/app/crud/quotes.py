"""Batched Redis-first quote retrieval."""

import json
from datetime import datetime
from typing import Any

import redis
import sqlalchemy as sa

from app.analytics.freshness import evaluate_freshness
from app.schemas.quote import CircuitState, QuoteDeltaPayload


def _decode(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode()
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _payload(row: dict[str, Any], current_ts: datetime, calendar: Any) -> QuoteDeltaPayload:
    quote_ts_value = row.get("as_of_ts") or row.get("quote_ts")
    if quote_ts_value is None:
        raise ValueError("quote payload is missing as_of_ts")
    quote_ts = quote_ts_value
    if isinstance(quote_ts, str):
        quote_ts = datetime.fromisoformat(quote_ts.replace("Z", "+00:00"))
    circuit = CircuitState(str(row.get("circuit_state", "NORMAL")))
    freshness, age = evaluate_freshness(
        quote_ts, current_ts, calendar, circuit is not CircuitState.NORMAL
    )
    ltp = row["ltp"]
    close = row.get("close", row.get("adj_prev_close", ltp))
    return QuoteDeltaPayload(
        symbol=str(row["symbol"]),
        ltp=ltp,
        change=row.get("change", ltp - close),
        change_pct=float(row.get("change_pct", 0.0)),
        open=row.get("open", ltp),
        high=row.get("high", ltp),
        low=row.get("low", ltp),
        close=close,
        volume=int(row.get("volume", 0)),
        turnover=row.get("turnover", 0),
        upper_band=row.get("upper_band"),
        lower_band=row.get("lower_band"),
        circuit_state=circuit,
        freshness_state=freshness,
        freshness_age_ms=age,
        as_of_ts=quote_ts,
        quality_flag=str(row.get("quality_flag", "OK")),
    )


def fetch_quotes_batch(
    db: Any,
    redis_client: Any,
    symbols: list[str],
    current_ts: datetime,
    calendar: Any,
) -> list[QuoteDeltaPayload]:
    ordered = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    keys = [f"quotes:{symbol}" for symbol in ordered]
    # Redis holds only a cache in front of Postgres — every value here is
    # rebuildable from market_quotes (§3.1, docker-compose.yml). An outage
    # degrades to reading Postgres directly rather than 500ing the endpoint.
    try:
        cached = redis_client.mget(keys)
    except redis.exceptions.RedisError:
        cached = [None] * len(keys)
    values: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for symbol, value in zip(ordered, cached, strict=True):
        decoded = _decode(value)
        if decoded is None:
            missing.append(symbol)
        else:
            values[symbol] = decoded
    if missing:
        try:
            rows = db.execute(
                sa.text("SELECT * FROM market_quotes WHERE symbol = ANY(:symbols)"),
                {"symbols": tuple(missing)},
            ).mappings()
            for row in rows:
                values[str(row["symbol"])] = dict(row)
        except sa.exc.DBAPIError:
            # A symbol with neither a cache entry nor a durable row is simply
            # absent from the response (see the final filter below) rather
            # than failing the whole batch — the same fail-open posture as
            # the Redis miss above.
            pass
        for symbol in missing:
            if symbol in values:
                try:
                    redis_client.set(
                        f"quotes:{symbol}", json.dumps(values[symbol], default=str), ex=60
                    )
                except redis.exceptions.RedisError:
                    pass
    return [
        _payload(values[symbol], current_ts, calendar)
        for symbol in ordered
        if symbol in values
    ]
