"""Common asynchronous quote-source contract."""

from collections.abc import AsyncIterator, Iterable
from typing import Protocol, runtime_checkable

from app.schemas.quote import QuoteDeltaPayload


@runtime_checkable
class QuoteSource(Protocol):
    @property
    def symbols(self) -> frozenset[str]: ...

    @property
    def is_running(self) -> bool: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def subscribe(self, symbols: Iterable[str]) -> None: ...

    async def unsubscribe(self, symbols: Iterable[str]) -> None: ...

    def stream_quotes(self) -> AsyncIterator[QuoteDeltaPayload]: ...

    def stream_batches(self) -> AsyncIterator[list[QuoteDeltaPayload]]: ...
