"""Stream consumer protocol."""

from collections.abc import AsyncIterator, Iterable
from typing import Protocol, runtime_checkable

from app.schemas.quote import QuoteDeltaPayload


@runtime_checkable
class StreamConsumer(Protocol):
    group_name: str
    consumer_name: str
    @property
    def is_running(self) -> bool: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def stream_batches(self) -> AsyncIterator[list[tuple[str, QuoteDeltaPayload]]]: ...

    async def ack(self, message_ids: Iterable[str]) -> None: ...
