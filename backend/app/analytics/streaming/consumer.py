"""Resilient Redis Streams consumer with reclaiming and DLQ containment."""

import inspect
import json
from collections.abc import AsyncIterator, Iterable
from typing import Any

from app.analytics.constants import (
    STREAM_CLAIM_MIN_IDLE_TIME_MS,
    STREAM_CONSUMER_BATCH_SIZE,
    STREAM_CONSUMER_BLOCK_MS,
    STREAM_MAX_DELIVERY_ATTEMPTS,
    STREAM_TICKS_DLQ_KEY,
    STREAM_TICKS_KEY,
)
from app.analytics.streaming.protocol import StreamConsumer
from app.schemas.quote import QuoteDeltaPayload


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class RedisStreamConsumer(StreamConsumer):
    def __init__(
        self,
        redis_client: Any,
        group_name: str,
        consumer_name: str,
        stream_key: str = STREAM_TICKS_KEY,
        dlq_key: str = STREAM_TICKS_DLQ_KEY,
        batch_size: int = STREAM_CONSUMER_BATCH_SIZE,
        block_ms: int = STREAM_CONSUMER_BLOCK_MS,
        claim_idle_ms: int = STREAM_CLAIM_MIN_IDLE_TIME_MS,
    ) -> None:
        self._redis = redis_client
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.stream_key = stream_key
        self.dlq_key = dlq_key
        self.batch_size = batch_size
        self.block_ms = block_ms
        self.claim_idle_ms = claim_idle_ms
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        try:
            await _maybe_await(
                self._redis.xgroup_create(
                    self.stream_key, self.group_name, id="0", mkstream=True
                )
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc).upper():
                raise
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def ack(self, message_ids: Iterable[str]) -> None:
        ids = list(message_ids)
        if ids:
            await _maybe_await(self._redis.xack(self.stream_key, self.group_name, *ids))

    async def _claim(self) -> list[tuple[str, QuoteDeltaPayload]]:
        response = await _maybe_await(
            self._redis.xautoclaim(
                self.stream_key,
                self.group_name,
                self.consumer_name,
                min_idle_time=self.claim_idle_ms,
                start_id="0-0",
                count=self.batch_size,
            )
        )
        entries = response[1] if isinstance(response, (list, tuple)) and len(response) > 1 else []
        return await self._decode_entries(entries)

    async def _decode_entries(self, entries: Any) -> list[tuple[str, QuoteDeltaPayload]]:
        decoded: list[tuple[str, QuoteDeltaPayload]] = []
        for raw_id, fields in entries:
            message_id = _text(raw_id)
            payload = fields.get(b"payload", fields.get("payload"))
            try:
                value = payload.decode() if isinstance(payload, bytes) else payload
                decoded.append((message_id, QuoteDeltaPayload.model_validate_json(value)))
            except (TypeError, ValueError, json.JSONDecodeError):
                pending = await _maybe_await(
                    self._redis.xpending_range(
                        self.stream_key, self.group_name, message_id, message_id, 1
                    )
                )
                attempts = _delivery_count(pending)
                if attempts >= STREAM_MAX_DELIVERY_ATTEMPTS:
                    await _maybe_await(
                        self._redis.xadd(self.dlq_key, {"payload": str(payload)})
                    )
                    await self.ack([message_id])
        return decoded

    async def stream_batches(self) -> AsyncIterator[list[tuple[str, QuoteDeltaPayload]]]:
        while self._running:
            claimed = await self._claim()
            if claimed:
                yield claimed
                continue
            result = await _maybe_await(
                self._redis.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    {self.stream_key: ">"},
                    count=self.batch_size,
                    block=self.block_ms,
                )
            )
            if not result:
                continue
            entries = result[0][1] if isinstance(result[0], (list, tuple)) else []
            batch = await self._decode_entries(entries)
            if batch:
                yield batch


def _delivery_count(pending: Any) -> int:
    if not pending:
        return 0
    item = pending[0]
    if isinstance(item, dict):
        value = item.get("times_delivered", item.get(b"times_delivered", 0))
        return int(value) if value is not None else 0
    return 0
