"""Redis Streams tick publisher."""

import inspect
from typing import Any

from app.analytics.constants import STREAM_TICKS_KEY, STREAM_TICKS_MAXLEN
from app.schemas.quote import QuoteDeltaPayload


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class RedisStreamTickPublisher:
    def __init__(
        self,
        redis_client: Any,
        stream_key: str = STREAM_TICKS_KEY,
        maxlen: int = STREAM_TICKS_MAXLEN,
    ) -> None:
        self._redis = redis_client
        self._stream_key = stream_key
        self._maxlen = maxlen

    async def publish_tick(self, quote: QuoteDeltaPayload) -> str:
        message_id = await _maybe_await(
            self._redis.xadd(
                self._stream_key,
                {"payload": quote.model_dump_json()},
                maxlen=self._maxlen,
                approximate=True,
            )
        )
        return message_id.decode() if isinstance(message_id, bytes) else str(message_id)

    async def publish_batch(self, quotes: list[QuoteDeltaPayload]) -> list[str]:
        pipeline = self._redis.pipeline()
        for quote in quotes:
            pipeline.xadd(
                self._stream_key,
                {"payload": quote.model_dump_json()},
                maxlen=self._maxlen,
                approximate=True,
            )
        results = await _maybe_await(pipeline.execute())
        return [
            result.decode() if isinstance(result, bytes) else str(result)
            for result in results
        ]
